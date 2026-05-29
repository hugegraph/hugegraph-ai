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
Process-wide runtime holder for the main asyncio event loop and shared
httpx.AsyncClient. Set once during FastAPI lifespan startup; read from
pycgraph pipeline nodes (which run on worker threads via
`await asyncio.to_thread(pipeline.run)`) so they can submit coroutines
back to the main loop via `asyncio.run_coroutine_threadsafe`.
"""

import asyncio
from typing import Optional

import httpx

_main_loop: Optional[asyncio.AbstractEventLoop] = None
_http_client: Optional[httpx.AsyncClient] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def get_main_loop() -> asyncio.AbstractEventLoop:
    if _main_loop is None:
        raise RuntimeError(
            "Main event loop not initialized. Ensure FastAPI lifespan ran "
            "(see hugegraph_llm.demo.rag_demo.other_block.lifespan)."
        )
    return _main_loop


def set_http_client(client: httpx.AsyncClient) -> None:
    global _http_client
    _http_client = client


def get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise RuntimeError("Shared httpx.AsyncClient not initialized. Ensure FastAPI lifespan ran.")
    return _http_client


def run_async_from_sync(coro, timeout: Optional[float] = None):
    """
    Submit a coroutine to the main event loop from a worker thread (e.g. pycgraph
    pipeline node) and block until it completes. Caller MUST be on a worker
    thread, NOT on the main event loop — calling this from the main loop will
    deadlock.

    To turn that "MUST" into a hard error rather than a silent hang, we detect
    the misuse at runtime: if the caller is on the same loop we'd dispatch to,
    ``fut.result()`` would block the loop that has to drive the coroutine, so
    we close the coroutine and raise instead.
    """
    main_loop = get_main_loop()
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is main_loop:
        coro.close()
        raise RuntimeError(
            "run_async_from_sync() must be called from a worker thread, not the "
            "main event loop — invoking it on the main loop would deadlock."
        )

    fut = asyncio.run_coroutine_threadsafe(coro, main_loop)
    return fut.result(timeout=timeout)
