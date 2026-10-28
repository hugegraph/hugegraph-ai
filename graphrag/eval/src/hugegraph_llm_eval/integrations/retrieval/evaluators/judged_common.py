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

"""Shared materialization and record lifecycle for judged retrieval metrics."""

from collections.abc import Callable
from datetime import datetime

from pydantic import JsonValue

from hugegraph_llm_eval.contracts.domain.artifacts import ArtifactRef
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationInput,
    EvaluationRecordDraft,
    Finding,
    Measurement,
    MeasurementDirection,
)
from hugegraph_llm_eval.contracts.errors import FailureCategory
from hugegraph_llm_eval.evaluation.judges.base import Judge
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.judges.lifecycle import JudgedEvaluatorLifecycle
from hugegraph_llm_eval.evaluation.judges.session import JudgeSession
from hugegraph_llm_eval.integrations.retrieval.materializers import (
    RETRIEVAL_COMPARISON_INPUT_SCHEMA,
    RetrievalArtifactMaterializer,
    RetrievalMaterializationError,
)
from hugegraph_llm_eval.integrations.retrieval.schemas import RetrievalComparisonInput


class JudgedRetrievalEvaluator(JudgedEvaluatorLifecycle):
    def __init__(
        self,
        materializer: RetrievalArtifactMaterializer,
        *,
        invocation_key: str,
        judge: Judge,
        prompt: JudgeContent,
        rubric: JudgeContent,
        clock: Callable[[], datetime],
    ) -> None:
        self._materializer = materializer
        super().__init__(
            namespace="retrieval",
            invocation_key=invocation_key,
            input_schema=RETRIEVAL_COMPARISON_INPUT_SCHEMA,
            judge=judge,
            prompt=prompt,
            rubric=rubric,
            clock=clock,
        )

    def materialize(self, evaluation_input: EvaluationInput) -> RetrievalComparisonInput | EvaluationRecordDraft:
        try:
            return self._materializer.comparison(evaluation_input)
        except RetrievalMaterializationError as exc:
            return self.failure("retrieval_materialization_failed", str(exc), FailureCategory.INVALID_INPUT)

    def completed(
        self,
        measurement: Measurement,
        findings: tuple[Finding, ...],
        reason: str,
        session: JudgeSession,
    ) -> EvaluationRecordDraft:
        return self.completed_record((measurement,), findings, reason, session)


def complete_indices(indices: tuple[int, ...], count: int) -> bool:
    return set(indices) == set(range(count)) and len(indices) == count


def require_unique_indices(indices: tuple[int, ...]) -> None:
    if len(indices) != len(set(indices)):
        raise ValueError("judge output indices must be unique")


def indexed(values: tuple[str, ...], index_name: str) -> list[JsonValue]:
    return [{index_name: index, "text": value} for index, value in enumerate(values)]


def ratio(name: str, value: float) -> Measurement:
    return Measurement(name=name, value=value, unit="ratio", direction=MeasurementDirection.HIGHER_IS_BETTER)


def subject(evaluation_input: EvaluationInput, port: str) -> ArtifactRef:
    return next(item.artifact for item in evaluation_input.subjects if item.port.value == port)
