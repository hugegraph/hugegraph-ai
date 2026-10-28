# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Small model contracts; no provider SDK or application configuration is imported."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Protocol


class Model(Protocol):
    def generate(self, *, prompt: str) -> str: ...


class AsyncModel(Protocol):
    async def agenerate(self, *, prompt: str) -> str: ...


def _is_async_callable(function) -> bool:
    """Recognize coroutine functions and callable objects without invoking them."""
    while isinstance(function, partial):
        function = function.func
    return inspect.iscoroutinefunction(function) or (
        callable(function) and inspect.iscoroutinefunction(function.__call__)
    )


class FunctionModel:
    """Adapt existing prompt-to-text functions without inheriting an SDK base class.

    Functions receive the prompt as their sole positional argument. Supply an
    asynchronous function for async calls, or explicitly use ThreadedModel.
    """

    def __init__(
        self,
        *,
        generate: Callable[[str], str] | None = None,
        agenerate: Callable[[str], Awaitable[str]] | None = None,
    ):
        if generate is None and agenerate is None:
            raise ValueError("Provide generate or agenerate.")
        if generate is not None and (not callable(generate) or _is_async_callable(generate)):
            raise TypeError("generate must be a synchronous callable; use agenerate for async functions.")
        if agenerate is not None and not callable(agenerate):
            raise TypeError("agenerate must be callable.")
        self._generate = generate
        self._agenerate = agenerate

    def generate(self, *, prompt: str) -> str:
        if self._generate is None:
            raise TypeError("This FunctionModel has no synchronous generate function.")
        return self._generate(prompt)

    async def agenerate(self, *, prompt: str) -> str:
        if self._agenerate is None:
            raise TypeError("This FunctionModel has no agenerate function; use ThreadedModel for synchronous models.")
        return await self._agenerate(prompt)


class ThreadedModel:
    """Explicitly run a synchronous model in a worker thread for async callers.

    Cancelling the awaiting task does not stop an already running model call.
    Use a model factory when processing several chunks concurrently.
    """

    def __init__(self, model: Model):
        try:
            require_model(model)
        except TypeError as exc:
            raise TypeError("ThreadedModel requires a synchronous generate method.") from exc
        self.model = model

    def generate(self, *, prompt: str) -> str:
        return self.model.generate(prompt=prompt)

    async def agenerate(self, *, prompt: str) -> str:
        return await asyncio.to_thread(self.model.generate, prompt=prompt)

    def close(self) -> None:
        close = getattr(self.model, "close", None)
        if callable(close):
            close()

    async def aclose(self) -> None:
        aclose = getattr(self.model, "aclose", None)
        if callable(aclose):
            await aclose()
        else:
            await asyncio.to_thread(self.close)


def require_model(model, *, asynchronous: bool = False) -> None:
    """Reject an incompatible model interface before starting inference."""
    method_name = "agenerate" if asynchronous else "generate"
    method = getattr(model, method_name, None)
    if not callable(method):
        raise TypeError(f"model must provide {method_name}(prompt=...).")
    if not asynchronous and _is_async_callable(method):
        raise TypeError("generate must be synchronous; use an async model and aextract_graph/adesign_schema.")
    if isinstance(model, FunctionModel) and getattr(model, f"_{method_name}") is None:
        raise TypeError(f"FunctionModel requires {method_name}; use ThreadedModel to adapt a synchronous model.")
