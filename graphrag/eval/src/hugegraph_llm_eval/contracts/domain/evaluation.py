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

"""Evaluation definitions, records, and Evaluator port."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

from pydantic import Field, JsonValue, field_validator, model_validator

from hugegraph_llm_eval.contracts.base import AwareDatetime, StrictModel, VersionedModel
from hugegraph_llm_eval.contracts.digests import ContentDigest, canonical_digest
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.judge import JudgeCallRecord, JudgeCallStatus
from hugegraph_llm_eval.contracts.domain.observation import SpanContextRef
from hugegraph_llm_eval.contracts.domain.operation import PortName
from hugegraph_llm_eval.contracts.errors import FailureDetail
from hugegraph_llm_eval.contracts.identity import (
    EvaluationInputId,
    EvaluationRecordId,
    EvaluationRunId,
    EvaluatorRef,
    ExecutionId,
    RunCaseId,
    SchemaRef,
)

MEASUREMENT_NAME_PATTERN = r"^[a-z][a-z0-9_.@-]*$"
MAX_CONCURRENCY = 8
MAX_SAMPLES = 8


class EvaluationRecordStatus(StrEnum):
    COMPLETED = "completed"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MeasurementDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    TARGET_IS_BETTER = "target_is_better"
    INFORMATIONAL = "informational"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Measurement(VersionedModel):
    name: str = Field(min_length=1, max_length=127, pattern=MEASUREMENT_NAME_PATTERN)
    value: float
    unit: str = Field(min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9_.-]*$")
    direction: MeasurementDirection = MeasurementDirection.INFORMATIONAL

    @field_validator("value")
    @classmethod
    def _require_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "measurement value must be finite"
            raise ValueError(msg)
        return value


class MetricDefinition(VersionedModel):
    """MetricDefinition — evaluator-authored contract declaring a metric name, unit, direction,
    tolerance, and optional target.

    Belongs here (contracts), not in reporting: evaluators declare their own metrics
    at registration-time and the definition is consumed by both reporting projections
    and the evaluation suite runtime itself."""

    name: str = Field(min_length=1, max_length=127, pattern=MEASUREMENT_NAME_PATTERN)
    invocation_key: str | None = Field(default=None, min_length=1, max_length=127, pattern=r"^[a-z][a-z0-9_.-]*$")
    unit: str = Field(min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9_.-]*$")
    direction: MeasurementDirection
    tolerance: float = Field(default=0, ge=0, allow_inf_nan=False)
    target: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate_target(self) -> "MetricDefinition":
        if self.direction is MeasurementDirection.TARGET_IS_BETTER and self.target is None:
            raise ValueError("target-is-better metric requires a target")
        if self.direction is not MeasurementDirection.TARGET_IS_BETTER and self.target is not None:
            raise ValueError("only target-is-better metric may declare a target")
        if self.direction is MeasurementDirection.INFORMATIONAL:
            raise ValueError("informational measurement cannot rank Runs")
        return self


class EvidenceLink(VersionedModel):
    artifact: ArtifactRef
    locator: str | None = Field(default=None, max_length=1_000)
    description: str | None = Field(default=None, max_length=2_000)


class Finding(VersionedModel):
    code: str = Field(min_length=1, max_length=127, pattern=r"^[a-z][a-z0-9_.-]*$")
    severity: FindingSeverity
    message: str = Field(min_length=1, max_length=4_000)
    evidence: tuple[EvidenceLink, ...] = ()


def _validate_record_failure(
    status: EvaluationRecordStatus,
    failure: FailureDetail | None,
) -> None:
    failed = {EvaluationRecordStatus.FAILED, EvaluationRecordStatus.CANCELLED}
    if status in failed and failure is None:
        msg = "failed or cancelled evaluation requires failure"
        raise ValueError(msg)
    if status not in failed and failure is not None:
        msg = "completed or not-applicable evaluation cannot contain failure"
        raise ValueError(msg)


class EvaluationRecordDraft(VersionedModel):
    invocation_key: str = Field(min_length=1, max_length=127, pattern=r"^[a-z][a-z0-9_.-]*$")
    evaluator: EvaluatorRef
    status: EvaluationRecordStatus
    measurements: tuple[Measurement, ...] = ()
    findings: tuple[Finding, ...] = ()
    reason: str = Field(min_length=1, max_length=8_000)
    judge_calls: tuple[JudgeCallRecord, ...] = ()
    attempts: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    failure: FailureDetail | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_status(self) -> "EvaluationRecordDraft":
        _validate_record_failure(self.status, self.failure)
        if self.status is not EvaluationRecordStatus.COMPLETED and self.measurements:
            msg = "only completed evaluation may contain measurements"
            raise ValueError(msg)
        indices = tuple(call.call_index for call in self.judge_calls)
        if indices != tuple(range(1, len(indices) + 1)):
            msg = "judge call indices must be contiguous and one-based"
            raise ValueError(msg)
        if self.status is EvaluationRecordStatus.COMPLETED and any(
            call.status is JudgeCallStatus.FAILED for call in self.judge_calls
        ):
            msg = "completed evaluation cannot contain a failed judge call"
            raise ValueError(msg)
        return self


class EvaluationRecord(EvaluationRecordDraft):
    record_id: EvaluationRecordId
    run_id: EvaluationRunId


class EvaluationRunSummary(VersionedModel):
    record_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    total_latency_ms: int = Field(ge=0)
    known_cost_usd: float = Field(ge=0)
    unknown_cost_records: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_counts(self) -> "EvaluationRunSummary":
        statuses = self.completed_count + self.not_applicable_count + self.failed_count + self.cancelled_count
        if statuses != self.record_count:
            msg = "evaluation summary status counts must equal record_count"
            raise ValueError(msg)
        if not math.isfinite(self.known_cost_usd):
            msg = "known evaluation cost must be finite"
            raise ValueError(msg)
        return self


def _validate_run_coverage(
    status: EvaluationRunStatus,
    required: int,
    completed: int,
) -> None:
    if completed > required:
        msg = "completed required count cannot exceed required count"
        raise ValueError(msg)
    if status is EvaluationRunStatus.COMPLETED and completed != required:
        msg = "completed evaluation run requires full required coverage"
        raise ValueError(msg)
    if status is EvaluationRunStatus.PARTIAL and not (0 < completed < required):
        msg = "partial evaluation run requires incomplete non-zero coverage"
        raise ValueError(msg)


def _validate_run_failure(
    status: EvaluationRunStatus,
    failure: FailureDetail | None,
) -> None:
    failed = {EvaluationRunStatus.FAILED, EvaluationRunStatus.CANCELLED}
    if status in failed and failure is None:
        msg = "failed or cancelled evaluation run requires failure"
        raise ValueError(msg)
    if status not in failed and failure is not None:
        msg = "non-failed evaluation run cannot contain failure"
        raise ValueError(msg)


class EvaluationSubject(StrictModel):
    port: PortName
    artifact: ArtifactRef


class EvaluationInput(VersionedModel):
    input_id: EvaluationInputId
    schema_ref: SchemaRef
    subjects: tuple[EvaluationSubject, ...] = Field(min_length=1)
    digest: ContentDigest

    @model_validator(mode="after")
    def _validate_subjects(self) -> "EvaluationInput":
        ports = tuple(subject.port.value for subject in self.subjects)
        if len(ports) != len(set(ports)):
            msg = "evaluation subject ports must be unique"
            raise ValueError(msg)
        expected = self._content_digest(self.schema_ref, self.subjects)
        if self.digest != expected or self.input_id != EvaluationInputId.from_digest(expected):
            msg = "evaluation input digest does not match subjects"
            raise ValueError(msg)
        return self

    @classmethod
    def create(
        cls,
        *,
        schema_ref: SchemaRef,
        subjects: tuple[EvaluationSubject, ...],
    ) -> "EvaluationInput":
        digest = cls._content_digest(schema_ref, subjects)
        return cls(
            input_id=EvaluationInputId.from_digest(digest),
            schema_ref=schema_ref,
            subjects=subjects,
            digest=digest,
        )

    @staticmethod
    def _content_digest(schema_ref: SchemaRef, subjects: tuple[EvaluationSubject, ...]) -> ContentDigest:
        return canonical_digest(
            {
                "schema": schema_ref.model_dump(mode="json"),
                "subjects": [
                    {"port": subject.port.value, "artifact_id": subject.artifact.artifact_id.value}
                    for subject in subjects
                ],
            }
        )


class EvaluatorDescriptor(VersionedModel):
    evaluator: EvaluatorRef
    implementation_digest: ContentDigest
    input_schema: SchemaRef
    output_schema: SchemaRef


class EvaluationDefinitionItem(VersionedModel):
    invocation_key: str = Field(min_length=1, max_length=127, pattern=r"^[a-z][a-z0-9_.-]*$")
    evaluator: EvaluatorRef
    implementation_digest: ContentDigest
    required: bool = True
    configuration_digest: ContentDigest | None = None


class EvaluationDefinition(VersionedModel):
    name: str = Field(min_length=1, max_length=127, pattern=r"^[a-z][a-z0-9_.-]*$")
    revision: str = Field(min_length=1, max_length=127, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    input_schema: SchemaRef
    items: tuple[EvaluationDefinitionItem, ...] = Field(min_length=1)
    digest: ContentDigest

    @model_validator(mode="after")
    def _validate_definition(self) -> "EvaluationDefinition":
        keys = tuple(item.invocation_key for item in self.items)
        if len(keys) != len(set(keys)):
            msg = "evaluation invocation keys must be unique"
            raise ValueError(msg)
        payload = self.model_dump(mode="json", exclude={"digest"})
        if self.digest != canonical_digest(payload):
            msg = "evaluation definition digest does not match content"
            raise ValueError(msg)
        return self

    @classmethod
    def create(
        cls,
        *,
        name: str,
        revision: str,
        input_schema: SchemaRef,
        items: tuple[EvaluationDefinitionItem, ...],
    ) -> "EvaluationDefinition":
        payload: JsonValue = {
            "schema_version": 1,
            "name": name,
            "revision": revision,
            "input_schema": input_schema.model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in items],
        }
        return cls(
            name=name,
            revision=revision,
            input_schema=input_schema,
            items=items,
            digest=canonical_digest(payload),
        )


class EvaluationCorrelation(StrictModel):
    run_case_id: RunCaseId | None = None
    execution_id: ExecutionId | None = None
    execution_attempt: int | None = Field(default=None, ge=0)
    plan_digest: ContentDigest | None = None
    source_completion_event_id: str | None = Field(default=None, min_length=3, max_length=255)
    subject_span: SpanContextRef | None = None

    @model_validator(mode="after")
    def _validate_execution(self) -> "EvaluationCorrelation":
        execution_details = (self.execution_attempt, self.source_completion_event_id, self.subject_span)
        if self.execution_id is None and any(value is not None for value in execution_details):
            raise ValueError("evaluation execution details require an Execution")
        if self.execution_id is not None and self.execution_attempt is None:
            raise ValueError("Execution-correlated evaluation requires an attempt")
        return self


class EvaluationRun(VersionedModel):
    run_id: EvaluationRunId
    request_key: str = Field(min_length=1, max_length=255)
    attempt: int = Field(ge=0)
    definition_digest: ContentDigest
    input_digest: ContentDigest
    status: EvaluationRunStatus
    record_ids: tuple[EvaluationRecordId, ...] = ()
    required_count: int = Field(ge=0)
    completed_required_count: int = Field(ge=0)
    supersedes_id: EvaluationRunId | None = None
    failure: FailureDetail | None = None
    summary: EvaluationRunSummary | None = None
    trace_context: SpanContextRef | None = None
    correlation: EvaluationCorrelation | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _validate_coverage(self) -> "EvaluationRun":
        if self.updated_at is not None and self.updated_at < self.created_at:
            msg = "evaluation run updated_at cannot precede created_at"
            raise ValueError(msg)
        if self.summary is not None and self.summary.record_count != len(self.record_ids):
            msg = "evaluation summary record_count must match record_ids"
            raise ValueError(msg)
        _validate_run_coverage(self.status, self.required_count, self.completed_required_count)
        _validate_run_failure(self.status, self.failure)
        return self


InputT = TypeVar("InputT")


class CancellationProbe(Protocol):
    @property
    def is_cancelled(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...


class ConcurrencyLimiter(Protocol):
    """Run-scoped cap shared by every provider call in one evaluation run."""

    def acquire(self, should_abort: Callable[[], FailureDetail | None]) -> FailureDetail | None:
        """Wait for a slot, or return the failure that ended the run while waiting."""
        ...

    def release(self) -> None:
        """Return a slot."""
        ...


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    run_id: EvaluationRunId
    request_key: str
    deadline: AwareDatetime | None
    cancellation: CancellationProbe
    max_concurrency: int = 1
    max_attempts: int = 1
    retry_backoff_seconds: float = 0
    limiter: ConcurrencyLimiter | None = None
    trace_context: SpanContextRef | None = None
    correlation: EvaluationCorrelation | None = None

    def __post_init__(self) -> None:
        if not self.request_key.strip() or len(self.request_key) > 255:
            msg = "request_key must contain 1 to 255 non-whitespace characters"
            raise ValueError(msg)
        if not 1 <= self.max_concurrency <= MAX_CONCURRENCY:
            msg = f"max_concurrency must be between 1 and {MAX_CONCURRENCY}"
            raise ValueError(msg)
        if not 1 <= self.max_attempts <= 20:
            msg = "max_attempts must be between 1 and 20"
            raise ValueError(msg)
        if not math.isfinite(self.retry_backoff_seconds) or self.retry_backoff_seconds < 0:
            msg = "retry_backoff_seconds must be finite and non-negative"
            raise ValueError(msg)


class Evaluator(Protocol[InputT]):
    descriptor: EvaluatorDescriptor
    input_type: type[InputT]

    def evaluate(self, evaluation_input: InputT, context: EvaluationContext) -> EvaluationRecordDraft: ...
