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

"""LLM-judged context entity recall and evidence attribution Evaluators."""

from collections.abc import Callable
from datetime import datetime

from pydantic import Field, model_validator

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecordDraft,
    EvidenceLink,
    Finding,
    FindingSeverity,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.evaluation.judges.base import Judge, JudgeCallError
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.retrieval.evaluators.judged_common import (
    JudgedRetrievalEvaluator,
    complete_indices,
    indexed,
    ratio,
    require_unique_indices,
    subject,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer


class ContextEntityVerdict(StrictModel):
    """LLM verdict for one answer entity against all retrieved contexts."""

    entity_index: int = Field(ge=0)
    entity: str = Field(min_length=1, max_length=4_000)
    covered: bool
    reason: str = Field(min_length=1, max_length=4_000)


class ContextEntityRecallOutput(StrictModel):
    """Direct semantic coverage judgements for entities in the reference answer."""

    has_reference_entities: bool
    verdicts: tuple[ContextEntityVerdict, ...]

    @model_validator(mode="after")
    def _complete_entity_decision(self) -> "ContextEntityRecallOutput":
        require_unique_indices(tuple(item.entity_index for item in self.verdicts))
        if self.has_reference_entities != bool(self.verdicts):
            raise ValueError("entity verdicts must agree with has_reference_entities")
        return self


class EvidenceVerdict(StrictModel):
    evidence_index: int = Field(ge=0)
    attributed: bool
    reason: str = Field(min_length=1, max_length=4_000)


class EvidenceRecallOutput(StrictModel):
    verdicts: tuple[EvidenceVerdict, ...]

    @model_validator(mode="after")
    def _unique_indices(self) -> "EvidenceRecallOutput":
        require_unique_indices(tuple(item.evidence_index for item in self.verdicts))
        return self


class ContextEntityRecallEvaluator(JudgedRetrievalEvaluator):
    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(
            materializer,
            invocation_key="context_entity_recall_llm",
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
        )

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        value = self.materialize(evaluation_input)
        if isinstance(value, EvaluationRecordDraft):
            return value
        session = self.session(context)
        if not value.reference.answer.strip():
            return self.completed(
                ratio("context_entity_recall_llm", 1), (), "reference answer has no entities", session
            )
        try:
            output = session.call(
                "judge_entity_coverage",
                self.request(
                    ContextEntityRecallOutput,
                    {
                        "question": value.query.question,
                        "reference_answer": value.reference.answer,
                        "contexts": indexed(value.candidate.contexts, "context_index"),
                    },
                ),
            )
        except JudgeCallError as exc:
            return self.judge_failure(exc, session)
        return self._complete_coverage(evaluation_input, output, session)

    def _complete_coverage(
        self,
        evaluation_input: EvaluationInput,
        output: ContextEntityRecallOutput,
        session: JudgeSession,
    ) -> EvaluationRecordDraft:
        """Convert a complete entity-coverage verdict into record facts."""
        if not output.has_reference_entities:
            return self.completed(
                ratio("context_entity_recall_llm", 1),
                (),
                "reference answer has no distinct entities",
                session,
            )
        if not complete_indices(tuple(item.entity_index for item in output.verdicts), len(output.verdicts)):
            return self.failure(
                "incomplete_context_entity_verdicts",
                "context entity judge must return contiguous verdict indices starting at zero",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        ordered = sorted(output.verdicts, key=lambda item: item.entity_index)
        covered = sum(item.covered for item in ordered)
        artifact = subject(evaluation_input, "retrieval_reference")
        return self.completed(
            ratio("context_entity_recall_llm", round(covered / len(ordered), 4)),
            _entity_findings(ordered, artifact),
            f"retrieved contexts semantically cover {covered} of {len(ordered)} reference entities",
            session,
        )


def _entity_findings(
    verdicts: list[ContextEntityVerdict],
    artifact: ArtifactRef,
) -> tuple[Finding, ...]:
    """Render entity-coverage verdicts as item-level findings."""
    return tuple(
        Finding(
            code="context_entity_recall.covered" if verdict.covered else "context_entity_recall.missing",
            severity=FindingSeverity.INFO if verdict.covered else FindingSeverity.ERROR,
            message=f"{verdict.entity}: {verdict.reason}",
            evidence=(EvidenceLink(artifact=artifact, locator=f"answer.entity[{verdict.entity_index}]"),),
        )
        for verdict in verdicts
    )


class EvidenceRecallEvaluator(JudgedRetrievalEvaluator):
    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        *,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(
            materializer,
            invocation_key="evidence_recall_llm",
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
        )

    def evaluate(self, evaluation_input: EvaluationInput, context: EvaluationContext) -> EvaluationRecordDraft:
        value = self.materialize(evaluation_input)
        if isinstance(value, EvaluationRecordDraft):
            return value
        session = self.session(context)
        evidence = value.reference.evidence
        artifact = subject(evaluation_input, "retrieval_reference")
        if not evidence:
            return self.completed(ratio("evidence_recall_llm", 1), (), "no reference evidence", session)
        if not value.candidate.contexts:
            findings = tuple(
                _finding(EvidenceVerdict(evidence_index=index, attributed=False, reason="no contexts"), artifact)
                for index in range(len(evidence))
            )
            return self.completed(ratio("evidence_recall_llm", 0), findings, "no retrieved contexts", session)
        try:
            output = session.call(
                "verify_evidence",
                self.request(
                    EvidenceRecallOutput,
                    {
                        "question": value.query.question,
                        "contexts": list(value.candidate.contexts),
                        "evidence": indexed(evidence, "evidence_index"),
                    },
                ),
            )
        except JudgeCallError as exc:
            return self.judge_failure(exc, session)
        if not complete_indices(tuple(item.evidence_index for item in output.verdicts), len(evidence)):
            return self.failure(
                "incomplete_evidence_verdicts",
                "evidence judge must return one verdict for every evidence index",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        ordered = sorted(output.verdicts, key=lambda item: item.evidence_index)
        attributed = sum(item.attributed for item in ordered)
        return self.completed(
            ratio("evidence_recall_llm", round(attributed / len(ordered), 4)),
            tuple(_finding(item, artifact) for item in ordered),
            f"retrieved contexts support {attributed} of {len(ordered)} reference evidence statements",
            session,
        )


def _finding(verdict: EvidenceVerdict, artifact: ArtifactRef) -> Finding:
    return Finding(
        code="evidence_recall.supported" if verdict.attributed else "evidence_recall.missing",
        severity=FindingSeverity.INFO if verdict.attributed else FindingSeverity.ERROR,
        message=verdict.reason,
        evidence=(EvidenceLink(artifact=artifact, locator=f"evidence[{verdict.evidence_index}]"),),
    )
