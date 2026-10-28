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

"""LLM-judged candidate faithfulness with complete item-level coverage."""

from collections.abc import Callable
from datetime import datetime

from pydantic import JsonValue

from hugegraph_llm_eval.contracts.digests import canonical_digest, canonical_json_bytes
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluatorDescriptor,
    EvidenceLink,
    Finding,
    FindingSeverity,
    Measurement,
    MeasurementDirection,
)
from hugegraph_llm_eval.contracts.domain.graph import (
    GraphCandidate,
    GraphExtractionInput,
    GraphReviewInput,
)
from hugegraph_llm_eval.contracts.domain.judge import (
    JudgeCallRecord,
    JudgeCallStatus,
    JudgeProvenance,
    ProviderUsage,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.contracts.identity import EvaluatorRef, SchemaRef
from hugegraph_llm_eval.evaluation.judges.base import (
    Judge,
    JudgeCallError,
    JudgeMessage,
    JudgeOptions,
    JudgeRequest,
)
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import (
    FaithfulnessIssueGroup as FaithfulnessIssueGroup,
)
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness_output import (
    FaithfulnessItemKind,
    FaithfulnessJudgeOutput,
    FaithfulnessVerdict,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import (
    GRAPH_EXTRACTION_INPUT_SCHEMA,
    GRAPH_REVIEW_INPUT_SCHEMA,
    QUALITY_INPUT_SCHEMAS,
    GraphArtifactMaterializer,
    GraphMaterializationError,
)

FAITHFULNESS_REF = EvaluatorRef(namespace="graph", name="faithfulness", revision="v1")
EXTRACTION_FAITHFULNESS_REF = EvaluatorRef(namespace="graph", name="faithfulness", revision="v2")


class FaithfulnessEvaluator:
    input_type = EvaluationInput

    def __init__(
        self,
        materializer: GraphArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
        input_schema: SchemaRef = GRAPH_REVIEW_INPUT_SCHEMA,
    ) -> None:
        if input_schema not in QUALITY_INPUT_SCHEMAS:
            raise ValueError("graph quality input schema must be candidate_review or extraction")
        self._materializer = materializer
        self._judge = judge
        self._prompt = prompt
        self._rubric = rubric
        self._clock = clock
        self._input_schema = input_schema
        self.descriptor = EvaluatorDescriptor(
            evaluator=_evaluator_ref(input_schema),
            implementation_digest=canonical_digest(_implementation_identity(judge, prompt, rubric, input_schema)),
            input_schema=input_schema,
            output_schema=SchemaRef(namespace="graph", name="faithfulness_record", version=1),
        )

    @property
    def invocation_key(self) -> str:
        return "faithfulness"

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        try:
            materialized = self._materialize(evaluation_input)
        except GraphMaterializationError as exc:
            return self._failure("graph_materialization_failed", str(exc), FailureCategory.INVALID_INPUT)
        if context.cancellation.is_cancelled:
            return self._failure(
                "evaluation_cancelled",
                context.cancellation.reason or "evaluation cancelled",
                FailureCategory.CANCELLED,
            )
        if not materialized.candidate.vertices and not materialized.candidate.edges:
            return self._empty_candidate()
        request = _judge_request(materialized, self._prompt, self._rubric)
        try:
            result = self._judge.judge(
                request,
                JudgeOptions(
                    deadline=context.deadline,
                    max_attempts=context.max_attempts,
                    initial_backoff_seconds=context.retry_backoff_seconds,
                ),
            )
        except JudgeCallError as exc:
            return self._judge_failure(exc)
        verdicts = result.output.verdicts()
        coverage_failure = _coverage_failure(materialized.candidate, verdicts)
        judge_call = _completed_judge_call(result.provenance, result.usage)
        if coverage_failure is not None:
            return self._failure(
                "incomplete_faithfulness_verdicts",
                coverage_failure,
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                judge_call=judge_call,
            )
        return self._completed(evaluation_input, verdicts, judge_call)

    def _completed(
        self,
        evaluation_input: EvaluationInput,
        verdicts: tuple[FaithfulnessVerdict, ...],
        judge_call: JudgeCallRecord,
    ) -> EvaluationRecordDraft:
        vertex_verdicts = tuple(item for item in verdicts if item.item_kind is FaithfulnessItemKind.VERTEX)
        edge_verdicts = tuple(item for item in verdicts if item.item_kind is FaithfulnessItemKind.EDGE)
        faithful_vertices = _faithful_count(vertex_verdicts)
        faithful_edges = _faithful_count(edge_verdicts)
        faithful = faithful_vertices + faithful_edges
        candidate = next(item.artifact for item in evaluation_input.subjects if item.port.value == "candidate_graph")
        findings = tuple(finding for item in verdicts for finding in _findings(item, candidate))
        score = faithful / len(verdicts)
        return EvaluationRecordDraft(
            invocation_key="faithfulness",
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.COMPLETED,
            measurements=_faithfulness_measurements(
                score,
                vertex_verdicts,
                faithful_vertices,
                edge_verdicts,
                faithful_edges,
            ),
            findings=findings,
            reason=(
                f"{faithful} of {len(verdicts)} extracted claims are supported by source evidence; "
                f"vertices {faithful_vertices}/{len(vertex_verdicts)}, "
                f"edges {faithful_edges}/{len(edge_verdicts)}"
            ),
            judge_calls=(judge_call,),
            attempts=1,
            latency_ms=_judge_call_latency(judge_call),
            created_at=self._clock(),
        )

    def _judge_failure(self, error: JudgeCallError) -> EvaluationRecordDraft:
        return self._failure(
            error.failure.code,
            error.failure.message,
            error.failure.category,
            retryable=error.failure.retryable,
            judge_call=_failed_judge_call(error),
        )

    def _failure(
        self,
        code: str,
        message: str,
        category: FailureCategory,
        *,
        retryable: bool = False,
        judge_call: JudgeCallRecord | None = None,
    ) -> EvaluationRecordDraft:
        failure = FailureDetail(category=category, code=code, message=message, retryable=retryable)
        return EvaluationRecordDraft(
            invocation_key="faithfulness",
            evaluator=self.descriptor.evaluator,
            status=(
                EvaluationRecordStatus.CANCELLED
                if category is FailureCategory.CANCELLED
                else EvaluationRecordStatus.FAILED
            ),
            reason=message,
            judge_calls=(judge_call,) if judge_call is not None else (),
            attempts=1,
            latency_ms=_judge_call_latency(judge_call) if judge_call is not None else 0,
            failure=failure,
            created_at=self._clock(),
        )

    def _empty_candidate(self) -> EvaluationRecordDraft:
        return EvaluationRecordDraft(
            invocation_key="faithfulness",
            evaluator=self.descriptor.evaluator,
            status=EvaluationRecordStatus.NOT_APPLICABLE,
            findings=(
                Finding(
                    code="faithfulness.empty_candidate",
                    severity=FindingSeverity.ERROR,
                    message="faithfulness is undefined because candidate graph contains no claims",
                ),
            ),
            reason="faithfulness is not applicable for an empty candidate graph",
            attempts=0,
            latency_ms=0,
            created_at=self._clock(),
        )

    def _materialize(self, evaluation_input: EvaluationInput) -> GraphReviewInput | GraphExtractionInput:
        """Use a complete input offline and preserve the no-GT production review boundary."""
        return self._materializer.quality(evaluation_input, expected_schema=self._input_schema)


def _faithful_count(verdicts: tuple[FaithfulnessVerdict, ...]) -> int:
    """Count supported claims in one graph item kind."""
    return sum(item.faithful for item in verdicts)


def _faithfulness_measurements(
    score: float,
    vertex_verdicts: tuple[FaithfulnessVerdict, ...],
    faithful_vertices: int,
    edge_verdicts: tuple[FaithfulnessVerdict, ...],
    faithful_edges: int,
) -> tuple[Measurement, ...]:
    """Return the micro score plus available per-kind diagnostics."""
    measurements = [
        Measurement(
            name="faithfulness",
            value=score,
            unit="ratio",
            direction=MeasurementDirection.HIGHER_IS_BETTER,
        ),
    ]
    for name, verdicts, faithful in (
        ("faithfulness_vertex", vertex_verdicts, faithful_vertices),
        ("faithfulness_edge", edge_verdicts, faithful_edges),
    ):
        if verdicts:
            measurements.append(
                Measurement(
                    name=name,
                    value=faithful / len(verdicts),
                    unit="ratio",
                    direction=MeasurementDirection.HIGHER_IS_BETTER,
                )
            )
    return tuple(measurements)


def _evaluator_ref(input_schema: SchemaRef) -> EvaluatorRef:
    """Keep offline extraction distinct from candidate-only production review."""
    return EXTRACTION_FAITHFULNESS_REF if input_schema == GRAPH_EXTRACTION_INPUT_SCHEMA else FAITHFULNESS_REF


def _implementation_identity(
    judge: Judge,
    prompt: JudgeContent,
    rubric: JudgeContent,
    input_schema: SchemaRef,
) -> JsonValue:
    return {
        "algorithm": "graph-item-faithfulness",
        "version": 6,
        "score_semantics": "supported_candidate_claims_micro_average_with_vertex_edge_diagnostics",
        "empty_candidate": "not_applicable",
        "input_schema": input_schema.model_dump(mode="json"),
        "judge": judge.descriptor.model_dump(mode="json"),
        "prompt": prompt.reference.model_dump(mode="json"),
        "rubric": rubric.reference.model_dump(mode="json"),
    }


def _completed_judge_call(provenance: JudgeProvenance, usage: ProviderUsage) -> JudgeCallRecord:
    return JudgeCallRecord(
        call_index=1,
        call_key="evaluate_items",
        status=JudgeCallStatus.COMPLETED,
        provenance=provenance,
        usage=usage,
    )


def _failed_judge_call(error: JudgeCallError) -> JudgeCallRecord:
    return JudgeCallRecord(
        call_index=1,
        call_key="evaluate_items",
        status=JudgeCallStatus.FAILED,
        provenance=error.provenance,
        failure=error.failure,
    )


def _judge_call_latency(call: JudgeCallRecord) -> int:
    return sum(attempt.latency_ms for attempt in call.provenance.attempts)


def _judge_request(
    materialized: GraphReviewInput | GraphExtractionInput,
    prompt: JudgeContent,
    rubric: JudgeContent,
) -> JudgeRequest[FaithfulnessJudgeOutput]:
    items = _items(materialized.candidate)
    payload = canonical_json_bytes({"source_text": materialized.source_text, "items": items}).decode()
    return JudgeRequest(
        messages=(
            JudgeMessage(
                role="system",
                content=f"{prompt.text}\n\nRubric:\n{rubric.text}",
            ),
            JudgeMessage(role="user", content=payload),
        ),
        response_type=FaithfulnessJudgeOutput,
        prompt=prompt.reference,
        rubric=rubric.reference,
    )


def _items(candidate: GraphCandidate) -> list[JsonValue]:
    vertices: list[JsonValue] = [
        {
            "item_kind": "vertex",
            "item_index": index,
            "label": vertex.label,
            "name": vertex.name,
            "properties": vertex.properties,
            "source_snippet": vertex.source_snippet,
        }
        for index, vertex in enumerate(candidate.vertices)
    ]
    edges: list[JsonValue] = [
        {
            "item_kind": "edge",
            "item_index": index,
            "label": edge.label,
            "out_v": edge.out_v,
            "in_v": edge.in_v,
            "out_v_label": edge.out_v_label,
            "in_v_label": edge.in_v_label,
            "properties": edge.properties,
            "source_snippet": edge.source_snippet,
        }
        for index, edge in enumerate(candidate.edges)
    ]
    return [*vertices, *edges]


def _coverage_failure(candidate: GraphCandidate, verdicts: tuple[FaithfulnessVerdict, ...]) -> str | None:
    expected = {
        *((FaithfulnessItemKind.VERTEX, index) for index in range(len(candidate.vertices))),
        *((FaithfulnessItemKind.EDGE, index) for index in range(len(candidate.edges))),
    }
    actual = {(item.item_kind, item.item_index) for item in verdicts}
    if actual == expected and len(actual) == len(verdicts):
        return None
    return "faithfulness judge must return exactly one verdict for every candidate vertex and edge"


def _findings(verdict: FaithfulnessVerdict, artifact: ArtifactRef) -> tuple[Finding, ...]:
    """Build the base finding and machine-readable category findings."""
    locator = (
        f"vertices[{verdict.item_index}]"
        if verdict.item_kind is FaithfulnessItemKind.VERTEX
        else f"edges[{verdict.item_index}]"
    )
    evidence = (EvidenceLink(artifact=artifact, locator=locator, description=verdict.evidence_quote),)
    base = Finding(
        code="faithfulness.supported" if verdict.faithful else "faithfulness.unsupported",
        severity=FindingSeverity.INFO if verdict.faithful else FindingSeverity.ERROR,
        message=(
            (verdict.support_reason or "supported claim")
            if verdict.faithful
            else (verdict.error_reason or "unsupported claim")
        ),
        evidence=evidence,
    )
    if verdict.faithful:
        return (base,)
    support_findings = (
        (
            Finding(
                code="faithfulness.supported_part",
                severity=FindingSeverity.INFO,
                message=verdict.support_reason,
                evidence=evidence,
            ),
        )
        if verdict.support_reason
        else ()
    )
    category_findings = tuple(
        Finding(
            code=f"faithfulness.issue.{category.value}",
            severity=FindingSeverity.ERROR,
            message=verdict.error_reason or "unsupported claim",
            evidence=evidence,
        )
        for category in verdict.error_categories
    )
    return (*support_findings, *category_findings, base)
