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

"""Context precision and graded relevancy Evaluators."""

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
from hugegraph_llm_eval.integrations.retrieval.evaluators.judged_common import (
    JudgedRetrievalEvaluator,
    complete_indices,
    indexed,
    ratio,
    require_unique_indices,
    subject,
)
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer


class ContextPrecisionVerdict(StrictModel):
    context_index: int = Field(ge=0)
    relevant: bool
    reason: str = Field(min_length=1, max_length=4_000)


class ContextPrecisionOutput(StrictModel):
    verdicts: tuple[ContextPrecisionVerdict, ...]

    @model_validator(mode="after")
    def _unique_indices(self) -> "ContextPrecisionOutput":
        require_unique_indices(tuple(item.context_index for item in self.verdicts))
        return self


class ContextRelevancyVerdict(StrictModel):
    context_index: int = Field(ge=0)
    score: int = Field(ge=0, le=2)
    reason: str = Field(min_length=1, max_length=4_000)


class ContextRelevancyOutput(StrictModel):
    verdicts: tuple[ContextRelevancyVerdict, ...]

    @model_validator(mode="after")
    def _unique_indices(self) -> "ContextRelevancyOutput":
        require_unique_indices(tuple(item.context_index for item in self.verdicts))
        return self


class ContextPrecisionEvaluator(JudgedRetrievalEvaluator):
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
            invocation_key="context_precision",
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
        contexts = value.candidate.contexts
        if not contexts:
            return self.completed(ratio("context_precision", 0), (), "no retrieved contexts", session)
        try:
            output = session.call(
                "judge_contexts",
                self.request(
                    ContextPrecisionOutput,
                    {
                        "question": value.query.question,
                        "ground_truth": value.reference.answer,
                        "contexts": indexed(contexts, "context_index"),
                    },
                ),
            )
        except JudgeCallError as exc:
            return self.judge_failure(exc, session)
        if not complete_indices(tuple(item.context_index for item in output.verdicts), len(contexts)):
            return self.failure(
                "incomplete_context_verdicts",
                "context precision judge must return one verdict for every context index",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        ordered = sorted(output.verdicts, key=lambda item: item.context_index)
        relevance = [int(item.relevant) for item in ordered]
        artifact = subject(evaluation_input, "retrieval_candidate")
        return self.completed(
            ratio("context_precision", round(_average_precision(relevance), 4)),
            tuple(_finding("context_precision", item, artifact) for item in ordered),
            f"{sum(relevance)} of {len(relevance)} contexts are relevant",
            session,
        )


class ContextRelevancyEvaluator(JudgedRetrievalEvaluator):
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
            invocation_key="context_relevancy",
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
        contexts = value.candidate.contexts
        if not contexts:
            return self.completed(ratio("context_relevancy", 0), (), "no retrieved contexts", session)
        try:
            output = session.call(
                "score_contexts",
                self.request(
                    ContextRelevancyOutput,
                    {"question": value.query.question, "contexts": indexed(contexts, "context_index")},
                ),
            )
        except JudgeCallError as exc:
            return self.judge_failure(exc, session)
        if not complete_indices(tuple(item.context_index for item in output.verdicts), len(contexts)):
            return self.failure(
                "incomplete_context_verdicts",
                "context relevancy judge must return one verdict for every context index",
                FailureCategory.INVALID_PROVIDER_OUTPUT,
                calls=session.calls,
            )
        ordered = sorted(output.verdicts, key=lambda item: item.context_index)
        score = sum(item.score for item in ordered) / (2 * len(ordered))
        artifact = subject(evaluation_input, "retrieval_candidate")
        return self.completed(
            ratio("context_relevancy", round(score, 4)),
            tuple(_finding("context_relevancy", item, artifact) for item in ordered),
            f"mean graded context relevance is {score:.4f}",
            session,
        )


def _average_precision(relevance: list[int]) -> float:
    relevant_count = sum(relevance)
    if not relevant_count:
        return 0.0
    hits = 0
    total = 0.0
    for rank, relevant in enumerate(relevance, start=1):
        if relevant:
            hits += 1
            total += hits / rank
    return total / relevant_count


def _finding(
    prefix: str,
    verdict: ContextPrecisionVerdict | ContextRelevancyVerdict,
    artifact: ArtifactRef,
) -> Finding:
    positive = verdict.relevant if isinstance(verdict, ContextPrecisionVerdict) else verdict.score > 0
    return Finding(
        code=f"{prefix}.relevant" if positive else f"{prefix}.irrelevant",
        severity=FindingSeverity.INFO if positive else FindingSeverity.WARNING,
        message=verdict.reason,
        evidence=(EvidenceLink(artifact=artifact, locator=f"contexts[{verdict.context_index}]"),),
    )
