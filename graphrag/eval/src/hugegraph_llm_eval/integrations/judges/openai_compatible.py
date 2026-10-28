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

"""OpenAI-compatible structured-output adapter with auditable attempts."""

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from pydantic import Field, JsonValue, field_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeProvenance,
    ProviderAttempt,
    ProviderAttemptStatus,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.evaluation.judges.base import (
    JudgeCallError,
    JudgeDescriptor,
    JudgeOptions,
    JudgeRequest,
    JudgeResult,
    OutputT,
)
from hugegraph_llm_eval.integrations.judges.openai_response import (
    AttemptFailureError,
    AttemptOutcome,
    OpenAIResponse,
    OpenAIResponseUsage,
    classify_exception,
    failure,
    provider_outcome,
)


class OpenAIParseTransport(Protocol):
    def parse(self, **kwargs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class OpenAICompatiblePricing:
    input_usd_per_million: float | None
    output_usd_per_million: float | None

    def __post_init__(self) -> None:
        values = (self.input_usd_per_million, self.output_usd_per_million)
        if any(value is not None and (not math.isfinite(value) or value < 0) for value in values):
            msg = "judge token pricing must be finite and non-negative"
            raise ValueError(msg)


class OpenAICompatibleSettings(StrictModel):
    temperature: float = Field(default=0, ge=0, le=2)
    seed: int | None = 42
    max_tokens: int = Field(default=131_072, ge=1)
    include_json_schema_instruction: bool = True
    extra_body: dict[str, JsonValue] | None = None

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "temperature must be finite"
            raise ValueError(msg)
        return value


def _backoff(options: JudgeOptions, attempt_index: int) -> float:
    return min(options.max_backoff_seconds, options.initial_backoff_seconds * (2.0 ** (attempt_index - 1)))


def _configuration_payload(
    settings: OpenAICompatibleSettings,
    pricing: OpenAICompatiblePricing,
) -> JsonValue:
    return {
        "generation": settings.model_dump(mode="json"),
        "pricing": {
            "input_usd_per_million": pricing.input_usd_per_million,
            "output_usd_per_million": pricing.output_usd_per_million,
        },
    }


def _structured_messages(
    request: JudgeRequest[OutputT],
    *,
    include_schema_instruction: bool,
) -> list[dict[str, object]]:
    messages = [message.model_dump(mode="json") for message in request.messages]
    if not include_schema_instruction:
        return messages
    schema = json.dumps(
        request.response_type.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    instruction = {
        "role": "system",
        "content": f"Return only valid JSON matching this JSON Schema: {schema}",
    }
    return [instruction, *messages]


class OpenAICompatibleJudge:
    """Adapts one chat-completions parse transport to the Judge port."""

    def __init__(
        self,
        *,
        transport: OpenAIParseTransport,
        descriptor: JudgeDescriptor,
        pricing: OpenAICompatiblePricing,
        settings: OpenAICompatibleSettings,
        clock: Callable[[], datetime],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self.descriptor = descriptor
        self._pricing = pricing
        self._settings = settings
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        expected = JudgeDescriptor.create(
            provider=descriptor.provider,
            model=descriptor.model,
            configuration=_configuration_payload(settings, pricing),
        )
        if descriptor.configuration_digest != expected.configuration_digest:
            msg = "JudgeDescriptor configuration digest does not match OpenAI-compatible settings"
            raise ValueError(msg)

    def judge(self, request: JudgeRequest[OutputT], options: JudgeOptions) -> JudgeResult[OutputT]:
        attempts: list[ProviderAttempt] = []
        for attempt_index in range(1, options.max_attempts + 1):
            timeout = self._remaining_seconds(options)
            if timeout is not None and timeout <= 0:
                failure_detail = failure(FailureCategory.TIMEOUT, "judge_deadline_exceeded", True)
                attempts.append(self._failed_attempt(attempt_index, 0, failure_detail))
                self._raise(request, attempts, failure_detail)
            started = self._monotonic()
            try:
                outcome = self._call(request, timeout)
            except Exception as exc:  # Provider transport and response parsing boundary.
                failure_detail = exc.failure if isinstance(exc, AttemptFailureError) else classify_exception(exc)
                latency_ms = self._latency_ms(started)
                attempts.append(self._failed_attempt(attempt_index, latency_ms, failure_detail))
                if not failure_detail.retryable or attempt_index == options.max_attempts:
                    self._raise(request, attempts, failure_detail)
                delay = _backoff(options, attempt_index)
                remaining = self._remaining_seconds(options)
                self._sleep(delay if remaining is None else min(delay, max(0, remaining)))
                continue
            attempts.append(self._completed_attempt(attempt_index, self._latency_ms(started), outcome.usage))
            provenance = self._provenance(
                request,
                attempts,
                response_id=outcome.response_id,
                response_model=outcome.response_model,
            )
            return JudgeResult(
                output=request.response_type.model_validate(outcome.output),
                provenance=provenance,
                usage=outcome.usage,
            )
        raise AssertionError("positive max_attempts guarantees a result or JudgeCallError")

    def _call(self, request: JudgeRequest[OutputT], timeout: float | None) -> AttemptOutcome:
        kwargs: dict[str, object] = {
            "model": self.descriptor.model,
            "messages": _structured_messages(
                request,
                include_schema_instruction=self._settings.include_json_schema_instruction,
            ),
            "response_format": request.response_type,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }
        if self._settings.seed is not None:
            kwargs["seed"] = self._settings.seed
        if self._settings.extra_body is not None:
            kwargs["extra_body"] = self._settings.extra_body
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = cast(OpenAIResponse, self._transport.parse(**kwargs))
        return provider_outcome(request, response, self._usage)

    def _usage(self, raw: OpenAIResponseUsage | None) -> ProviderUsage:
        input_tokens = raw.prompt_tokens if raw is not None else 0
        output_tokens = raw.completion_tokens if raw is not None else 0
        if raw is not None and raw.total_tokens != input_tokens + output_tokens:
            failure_detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "inconsistent_provider_usage", False)
            raise AttemptFailureError(failure_detail)
        cost = None
        rates = (self._pricing.input_usd_per_million, self._pricing.output_usd_per_million)
        if raw is not None and all(rate is not None for rate in rates):
            input_rate = cast(float, self._pricing.input_usd_per_million)
            output_rate = cast(float, self._pricing.output_usd_per_million)
            cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
        return ProviderUsage(
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost,
            reported=raw is not None,
        )

    def _completed_attempt(
        self,
        attempt_index: int,
        latency_ms: int,
        usage: ProviderUsage,
    ) -> ProviderAttempt:
        return ProviderAttempt(
            attempt_index=attempt_index,
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            status=ProviderAttemptStatus.COMPLETED,
            latency_ms=latency_ms,
            usage=usage,
        )

    def _failed_attempt(
        self,
        attempt_index: int,
        latency_ms: int,
        failure: FailureDetail,
    ) -> ProviderAttempt:
        return ProviderAttempt(
            attempt_index=attempt_index,
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            status=ProviderAttemptStatus.FAILED,
            latency_ms=latency_ms,
            failure=failure,
        )

    def _provenance(
        self,
        request: JudgeRequest[OutputT],
        attempts: list[ProviderAttempt],
        response_id: str | None,
        response_model: str | None,
    ) -> JudgeProvenance:
        return JudgeProvenance(
            provider=self.descriptor.provider,
            model=self.descriptor.model,
            configuration_digest=self.descriptor.configuration_digest,
            prompt=request.prompt,
            rubric=request.rubric,
            attempts=tuple(attempts),
            response_id=response_id,
            response_model=response_model,
        )

    def _raise(
        self,
        request: JudgeRequest[OutputT],
        attempts: list[ProviderAttempt],
        failure: FailureDetail,
    ) -> None:
        raise JudgeCallError(
            failure,
            self._provenance(request, attempts, response_id=None, response_model=None),
        )

    def _remaining_seconds(self, options: JudgeOptions) -> float | None:
        if options.deadline is None:
            return None
        return (options.deadline - self._clock()).total_seconds()

    def _latency_ms(self, started: float) -> int:
        return max(0, round((self._monotonic() - started) * 1_000))
