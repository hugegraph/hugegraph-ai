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

"""Application-independent graph extraction entrypoints."""

import inspect
from collections.abc import Callable, Iterable, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Literal

from hugegraph_llm_core._lifecycle import OwnedModels
from hugegraph_llm_core.errors import SchemaValidationError
from hugegraph_llm_core.extraction_runtime.property_graph import PropertyGraphBundle
from hugegraph_llm_core.extraction_runtime.review import (
    ChunkInput,
    ChunkResult,
    ExtractionOptions,
    Issue,
    arun_chunks,
    run_chunks,
)
from hugegraph_llm_core.models import AsyncModel, Model, _is_async_callable, require_model
from hugegraph_llm_core.prompts import GraphPrompts
from hugegraph_llm_core.schema import validate_schema


@dataclass
class ExtractionResult:
    """Ordered chunk diagnostics and a concatenation of completed chunk graphs.

    No cross-chunk identity resolution or deduplication is performed. Inspect
    status and chunks before deciding whether to persist a partial result.
    """

    status: Literal["succeeded", "partial", "failed"]
    chunks: tuple[ChunkResult, ...]
    graph: dict

    def as_dict(self) -> dict:
        return asdict(self)


def _prepare_inputs(
    texts, schema, model, model_factory, review, options, prompts, validators, resources, *, asynchronous
):
    if (model is None) == (model_factory is None):
        raise ValueError("Provide exactly one of model or model_factory.")
    if model_factory is not None and not callable(model_factory):
        raise TypeError("model_factory must be a callable taking no arguments.")
    if model_factory is not None and _is_async_callable(model_factory):
        raise TypeError("model_factory must be synchronous and return a model, not a coroutine.")
    if not isinstance(review, bool):
        raise TypeError("review must be a bool.")
    if isinstance(texts, str):
        texts = [texts]
    if not isinstance(texts, (list, tuple)) or not texts:
        raise ValueError("texts must be a non-empty string or sequence of text chunks.")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("Every text chunk must be a non-empty string.")
    chunks = tuple(ChunkInput(index, text) for index, text in enumerate(texts))
    if options is None:
        options = ExtractionOptions()
    elif not isinstance(options, ExtractionOptions):
        raise TypeError("options must be ExtractionOptions.")
    # Revalidate a copied options object, including objects modified after creation.
    options = ExtractionOptions.model_validate(options.model_dump())
    if options.max_workers > 1 and model_factory is None:
        raise ValueError("Concurrent extraction requires model_factory to create an independent model per chunk.")
    if prompts is not None and not isinstance(prompts, GraphPrompts):
        raise TypeError("prompts must be GraphPrompts.")
    prompts = prompts if prompts is not None else GraphPrompts()
    validators = tuple(validators)
    if any(not callable(validator) for validator in validators):
        raise TypeError("validators must contain callable validators.")
    if any(_is_async_callable(validator) for validator in validators):
        raise TypeError("validators must be synchronous local checks.")
    schema = deepcopy(schema)
    issues = validate_schema(schema)
    if issues:
        raise SchemaValidationError(issues)
    if model is not None:
        require_model(model, asynchronous=asynchronous)

    def prepare(_chunk):
        chunk_model = model_factory() if model_factory is not None else model
        if inspect.isawaitable(chunk_model):
            if inspect.iscoroutine(chunk_model):
                chunk_model.close()
            raise TypeError("model_factory must return a model, not an awaitable.")
        if model_factory is not None:
            resources.add(chunk_model)
        require_model(chunk_model, asynchronous=asynchronous)
        return PropertyGraphBundle(llm=chunk_model, schema=schema, prompts=prompts, validators=validators)

    return chunks, prepare, options


def _aggregate(chunks: tuple[ChunkResult, ...], *, review: bool) -> ExtractionResult:
    completed_status = "final" if review else "validated"
    completed = [chunk for chunk in chunks if chunk.status == completed_status]
    status = "succeeded" if len(completed) == len(chunks) else "partial" if completed else "failed"
    graph = {key: [deepcopy(item) for chunk in completed for item in chunk.graph[key]] for key in ("vertices", "edges")}
    return ExtractionResult(status=status, chunks=chunks, graph=graph)


def extract_graph(
    texts: str | Sequence[str],
    *,
    schema: dict,
    model: Model | None = None,
    model_factory: Callable[[], Model] | None = None,
    review: bool = True,
    options: ExtractionOptions | None = None,
    prompts: GraphPrompts | None = None,
    validators: Iterable[Callable[[dict, dict, str], list[Issue]]] = (),
) -> ExtractionResult:
    """Extract reviewed property graphs without a database, UI or global config.

    Strings are single chunks; lists preserve caller-provided boundaries. Model
    instances execute serially. Pass a factory and explicit max_workers for
    concurrency. Invalid input raises before inference; chunk failures are data.
    """
    resources = OwnedModels()
    chunks, prepare, effective_options = _prepare_inputs(
        texts, schema, model, model_factory, review, options, prompts, validators, resources, asynchronous=False
    )
    # Close factory clients on the caller's thread before starting another
    # bounded group. Completed chunks must not accumulate open connections.
    group_size = effective_options.max_workers if model_factory is not None else len(chunks)
    results = []
    for start in range(0, len(chunks), group_size):
        with resources:
            results.extend(
                run_chunks(
                    chunks=chunks[start : start + group_size],
                    prepare=prepare,
                    options=effective_options,
                    review=review,
                )
            )
    return _aggregate(tuple(results), review=review)


async def aextract_graph(
    texts: str | Sequence[str],
    *,
    schema: dict,
    model: AsyncModel | None = None,
    model_factory: Callable[[], AsyncModel] | None = None,
    review: bool = True,
    options: ExtractionOptions | None = None,
    prompts: GraphPrompts | None = None,
    validators: Iterable[Callable[[dict, dict, str], list[Issue]]] = (),
) -> ExtractionResult:
    """Native asynchronous extraction; cancellation propagates to the caller.

    A synchronous model requires an explicit ThreadedModel adapter. Factories
    construct models synchronously and must not perform blocking I/O.
    """
    resources = OwnedModels()
    chunks, prepare, effective_options = _prepare_inputs(
        texts, schema, model, model_factory, review, options, prompts, validators, resources, asynchronous=True
    )
    group_size = effective_options.max_workers if model_factory is not None else len(chunks)
    results = []
    for start in range(0, len(chunks), group_size):
        # arun_chunks stops and awaits all group workers before client cleanup,
        # including when inference is cancelled.
        async with resources:
            results.extend(
                await arun_chunks(
                    chunks=chunks[start : start + group_size],
                    prepare=prepare,
                    options=effective_options,
                    review=review,
                )
            )
    return _aggregate(tuple(results), review=review)
