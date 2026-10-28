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

"""Flat observation facts and durable Operation completion contracts."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from hugegraph_llm_eval.contracts.base import AwareDatetime, StrictModel, VersionedModel
from hugegraph_llm_eval.contracts.digests import ContentDigest, canonical_digest
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.operation import OperationRef, PortName
from hugegraph_llm_eval.contracts.errors import FailureDetail
from hugegraph_llm_eval.contracts.identity import ExecutionId, ObservationDeliveryId, RunCaseId


class ObservationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class SpanStatus(StrEnum):
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class SpanRole(StrEnum):
    INTERNAL = "internal"
    OPERATION = "operation"
    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    RETRIEVAL = "retrieval"
    REVIEW = "review"
    EVALUATION = "evaluation"


class SpanKind(StrEnum):
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanContextRef(StrictModel):
    trace_id: str
    span_id: str
    trace_flags: int = Field(default=0, ge=0, le=255)
    trace_state: str = Field(default="", max_length=512)
    is_remote: bool = False

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, value: str) -> str:
        if len(value) != 32 or value == "0" * 32 or any(char not in "0123456789abcdef" for char in value):
            msg = "trace_id must be 32 lowercase hex characters and non-zero"
            raise ValueError(msg)
        return value

    @field_validator("span_id")
    @classmethod
    def _validate_span_id(cls, value: str) -> str:
        if len(value) != 16 or value == "0" * 16 or any(char not in "0123456789abcdef" for char in value):
            msg = "span_id must be 16 lowercase hex characters and non-zero"
            raise ValueError(msg)
        return value


class OperationOccurrence(StrictModel):
    instance_key: str = Field(default="default", min_length=1, max_length=255)
    business_iteration: int = Field(default=0, ge=0)
    occurrence: int = Field(default=0, ge=0)


class OperationOutput(StrictModel):
    port: PortName
    artifact: ArtifactRef


class AgentSpanDetails(StrictModel):
    kind: Literal["agent"] = "agent"
    agent_name: str = Field(min_length=1, max_length=255)
    available_tools: tuple[str, ...] = ()
    handoffs: tuple[str, ...] = ()


class LLMSpanDetails(StrictModel):
    kind: Literal["llm"] = "llm"
    provider: str | None = Field(default=None, min_length=1, max_length=127)
    request_model: str | None = Field(default=None, min_length=1, max_length=255)
    response_model: str | None = Field(default=None, min_length=1, max_length=255)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    prompt_digest: ContentDigest | None = None


class ToolSpanDetails(StrictModel):
    kind: Literal["tool"] = "tool"
    tool_name: str = Field(min_length=1, max_length=255)
    input_artifact: ArtifactRef | None = None
    output_artifact: ArtifactRef | None = None


class RetrievalSpanDetails(StrictModel):
    kind: Literal["retrieval"] = "retrieval"
    top_k: int | None = Field(default=None, ge=1)
    query_artifact: ArtifactRef | None = None
    result_artifact: ArtifactRef | None = None


SpanDetails = Annotated[
    AgentSpanDetails | LLMSpanDetails | ToolSpanDetails | RetrievalSpanDetails,
    Field(discriminator="kind"),
]


class SpanCapturePolicy(VersionedModel):
    captured_detail_roles: tuple[SpanRole, ...]
    digest: ContentDigest

    @classmethod
    def create(cls, captured_detail_roles: tuple[SpanRole, ...]) -> "SpanCapturePolicy":
        roles = tuple(sorted(set(captured_detail_roles), key=lambda role: role.value))
        digest = canonical_digest({"captured_detail_roles": [role.value for role in roles]})
        return cls(captured_detail_roles=roles, digest=digest)

    @model_validator(mode="after")
    def _validate_digest(self) -> "SpanCapturePolicy":
        roles = tuple(sorted(set(self.captured_detail_roles), key=lambda role: role.value))
        if roles != self.captured_detail_roles:
            raise ValueError("captured detail roles must be unique and sorted")
        supported = {SpanRole.AGENT, SpanRole.LLM, SpanRole.TOOL, SpanRole.RETRIEVAL}
        if not set(roles).issubset(supported):
            raise ValueError("capture policy roles must support typed Span details")
        expected = canonical_digest({"captured_detail_roles": [role.value for role in roles]})
        if self.digest != expected:
            raise ValueError("Span capture policy digest does not match its roles")
        return self


def _require_unique_ports(outputs: tuple[OperationOutput, ...], *, subject: str) -> None:
    names = tuple(output.port.value for output in outputs)
    if len(names) != len(set(names)):
        msg = f"{subject} names must be unique"
        raise ValueError(msg)


class OperationCompletion(VersionedModel):
    event_id: str = Field(min_length=3, max_length=255, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")
    execution_id: ExecutionId
    operation: OperationRef
    occurrence: OperationOccurrence
    outputs: tuple[OperationOutput, ...] = Field(min_length=1)
    span: SpanContextRef | None = None
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_outputs(self) -> "OperationCompletion":
        _require_unique_ports(self.outputs, subject="Operation completion output port")
        return self


class SpanLink(StrictModel):
    context: SpanContextRef
    relationship: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")


class SpanRecord(VersionedModel):
    context: SpanContextRef
    execution_id: ExecutionId | None = None
    run_case_id: RunCaseId | None = None
    attempt_index: int | None = Field(default=None, ge=0)
    parent: SpanContextRef | None = None
    links: tuple[SpanLink, ...] = ()
    name: str = Field(min_length=1, max_length=255)
    kind: SpanKind = SpanKind.INTERNAL
    role: SpanRole
    details: SpanDetails | None = None
    status: SpanStatus
    operation: OperationRef | None = None
    occurrence: OperationOccurrence | None = None
    configuration_digest: ContentDigest | None = None
    implementation_digest: ContentDigest | None = None
    inputs: tuple[OperationOutput, ...] = ()
    outputs: tuple[OperationOutput, ...] = ()
    instrumentation_scope_name: str | None = Field(default=None, max_length=255)
    instrumentation_scope_version: str | None = Field(default=None, max_length=127)
    dropped_attributes: int = Field(default=0, ge=0)
    dropped_events: int = Field(default=0, ge=0)
    dropped_links: int = Field(default=0, ge=0)
    failure: FailureDetail | None = None
    started_at: AwareDatetime
    ended_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_semantics(self) -> "SpanRecord":
        _validate_span_timing(self)
        _validate_span_execution(self)
        _validate_span_operation_identity(self)
        _validate_span_ports(self)
        _validate_span_failure(self)
        _validate_span_details(self)
        return self


def _validate_span_execution(span: SpanRecord) -> None:
    if (span.execution_id is None) != (span.attempt_index is None):
        msg = "Span execution_id and attempt_index must either both be present or both be absent"
        raise ValueError(msg)
    if span.execution_id is None and span.run_case_id is not None:
        msg = "Span run_case_id requires an Execution"
        raise ValueError(msg)
    if span.execution_id is None and span.role is not SpanRole.EVALUATION:
        msg = "only Evaluation spans may exist without a managed Execution"
        raise ValueError(msg)


def _validate_span_timing(span: SpanRecord) -> None:
    if span.ended_at < span.started_at:
        msg = "ended_at cannot precede started_at"
        raise ValueError(msg)


def _validate_span_operation_identity(span: SpanRecord) -> None:
    has_complete_identity = span.operation is not None and span.occurrence is not None
    has_any_identity = span.operation is not None or span.occurrence is not None
    if span.role is SpanRole.OPERATION and not has_complete_identity:
        msg = "operation spans require operation and occurrence"
        raise ValueError(msg)
    if span.role is not SpanRole.OPERATION and has_any_identity:
        msg = "only operation spans may carry operation identity"
        raise ValueError(msg)


def _validate_span_ports(span: SpanRecord) -> None:
    if span.role is not SpanRole.OPERATION and (span.inputs or span.outputs):
        msg = "only operation spans may carry named Artifact ports"
        raise ValueError(msg)
    _require_unique_ports(span.inputs, subject="Span input Artifact port")
    _require_unique_ports(span.outputs, subject="Span output Artifact port")


def _validate_span_failure(span: SpanRecord) -> None:
    if span.status is SpanStatus.ERROR and span.failure is None:
        msg = "error Span requires a redacted failure classification"
        raise ValueError(msg)
    if span.status is not SpanStatus.ERROR and span.failure is not None:
        msg = "non-error Span cannot contain failure"
        raise ValueError(msg)


def _validate_span_details(span: SpanRecord) -> None:
    if span.details is None:
        return
    if span.details.kind != span.role.value:
        msg = "Span details kind must match Span role"
        raise ValueError(msg)


class ObservationDelivery(VersionedModel):
    delivery_id: ObservationDeliveryId
    execution_id: ExecutionId
    attempt: int = Field(ge=0)
    status: ObservationStatus
    drained: int = Field(ge=0)
    queued: int = Field(ge=0)
    dropped: int = Field(ge=0)
    timed_out: bool = False
    failures: tuple[FailureDetail, ...] = ()
    supersedes_id: ObservationDeliveryId | None = None
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def _validate_status(self) -> "ObservationDelivery":
        has_loss = _delivery_has_loss(self)
        _validate_completed_delivery(self, has_loss=has_loss)
        _validate_failed_delivery(self)
        _validate_partial_delivery(self, has_loss=has_loss)
        _validate_not_applicable_delivery(self)
        return self


def _delivery_has_loss(delivery: ObservationDelivery) -> bool:
    return delivery.queued > 0 or delivery.dropped > 0 or delivery.timed_out or bool(delivery.failures)


def _validate_completed_delivery(delivery: ObservationDelivery, *, has_loss: bool) -> None:
    if delivery.status is ObservationStatus.COMPLETED and (has_loss or delivery.drained == 0):
        msg = "completed observation delivery requires drained Spans and no loss"
        raise ValueError(msg)


def _validate_failed_delivery(delivery: ObservationDelivery) -> None:
    if delivery.status is ObservationStatus.FAILED and not delivery.failures:
        msg = "failed observation delivery requires failure details"
        raise ValueError(msg)


def _validate_partial_delivery(delivery: ObservationDelivery, *, has_loss: bool) -> None:
    if delivery.status is ObservationStatus.PARTIAL and (delivery.drained == 0 or not has_loss):
        msg = "partial observation delivery requires drained Spans and explicit loss"
        raise ValueError(msg)


def _validate_not_applicable_delivery(delivery: ObservationDelivery) -> None:
    has_activity = delivery.drained or delivery.queued or delivery.dropped or delivery.timed_out or delivery.failures
    if delivery.status is ObservationStatus.NOT_APPLICABLE and has_activity:
        msg = "not-applicable observation delivery cannot report work or loss"
        raise ValueError(msg)
