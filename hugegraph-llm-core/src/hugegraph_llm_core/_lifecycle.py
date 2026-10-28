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

"""Batch ownership for models created by a caller-supplied factory."""

import asyncio
import logging
import threading

log = logging.getLogger(__name__)


class OwnedModels:
    def __init__(self):
        self._models = []
        # Keep identities across groups so a factory cannot reuse a closed
        # model. Strong references also prevent false matches from reused ids.
        self._seen = {}
        self._lock = threading.Lock()

    def add(self, model):
        with self._lock:
            if id(model) in self._seen:
                raise ValueError("model_factory must create an independent model for each chunk.")
            self._seen[id(model)] = model
            self._models.append(model)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        errors = []
        models, self._models = self._models, []
        for model in reversed(models):
            close = getattr(model, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as error:
                    errors.append(error)
        self._finish(errors, exc_type)
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        # Once ownership ends, finish closing every client even if the caller
        # cancels during cleanup (or cancels again while cleanup is pending).
        cleanup = asyncio.create_task(self._aclose_all())
        cancellation = None
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError as error:
                cancellation = error
        errors, close_cancellation = cleanup.result()
        if cancellation is None and exc_type is None:
            cancellation = close_cancellation
        self._finish(errors, type(cancellation) if cancellation is not None else exc_type)
        if cancellation is not None:
            raise cancellation
        return False

    async def _aclose_all(self):
        errors = []
        cancellation = None
        models, self._models = self._models, []
        for model in reversed(models):
            aclose = getattr(model, "aclose", None)
            close = getattr(model, "close", None)
            try:
                if callable(aclose):
                    await aclose()
                elif callable(close):
                    await asyncio.to_thread(close)
            except asyncio.CancelledError as error:
                # A client's own cancelled task must not skip sibling clients.
                cancellation = error
            except Exception as error:
                errors.append(error)
        return errors, cancellation

    @staticmethod
    def _finish(errors, primary_error_type):
        if not errors:
            return
        if primary_error_type is None:
            raise RuntimeError("Failed to close a model created by model_factory.") from errors[0]
        # Preserve the original failure, particularly asyncio cancellation.
        log.warning(
            "Model cleanup failed while handling %s (%s)", primary_error_type.__name__, type(errors[0]).__name__
        )
