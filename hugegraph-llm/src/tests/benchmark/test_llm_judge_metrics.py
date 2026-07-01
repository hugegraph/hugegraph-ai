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

"""Tests for LLM Judge metrics: Faithfulness, AnswerCorrectness,
ContextPrecision, ContextRelevancy, EvidenceRecallLLM."""

import json

import pytest

from hugegraph_llm.benchmark.metrics.answer.answer_correctness import AnswerCorrectness
from hugegraph_llm.benchmark.metrics.answer.faithfulness import Faithfulness
from hugegraph_llm.benchmark.metrics.retrieval.context_precision import ContextPrecision
from hugegraph_llm.benchmark.metrics.retrieval.context_relevancy import ContextRelevancy
from hugegraph_llm.benchmark.metrics.retrieval.evidence_recall import EvidenceRecallLLM

pytestmark = pytest.mark.unit


class FakeLLM:
    """Simple fake LLM that returns pre-configured responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    def generate(self, prompt='', **kwargs):
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return '{}'


def test_faithfulnessoffline_faithfulness_offline():
    metric = Faithfulness()
    # No LLM -> faithfulness is None.
    result = metric.calculate(
        'Paris is the capital of France', llm=None, context=['Some context'], question='What is the capital of France?'
    )
    assert result['faithfulness'] is None


def test_answercorrectnessoffline_answer_correctness_offline():
    metric = AnswerCorrectness()
    # No LLM -> all values None.
    result = metric.calculate(
        'Paris is the capital of France',
        reference='Paris is the capital of France',
        llm=None,
        question='What is the capital of France?',
    )
    assert result['answer_correctness'] is None
    assert result['answer_tp'] is None
    assert result['answer_fp'] is None
    assert result['answer_fn'] is None


def test_contextprecisionoffline_context_precision_offline():
    metric = ContextPrecision()
    # No LLM -> context_precision is None.
    result = metric.calculate(
        ['context1', 'context2'], reference='ground truth', llm=None, question='What is the capital of France?'
    )
    assert result['context_precision'] is None


def test_contextrelevancyoffline_context_relevancy_offline():
    metric = ContextRelevancy()
    # No LLM -> context_relevancy is None.
    result = metric.calculate(['context1', 'context2'], llm=None, question='What is the capital of France?')
    assert result['context_relevancy'] is None


def test_evidencerecalloffline_evidence_recall_offline():
    metric = EvidenceRecallLLM()
    # No LLM -> evidence_recall_llm is None.
    result = metric.calculate(['context1'], reference=['evidence1'], llm=None)
    assert result['evidence_recall_llm'] is None


def test_faithfulnesswithfakellm_faithfulness_with_fake_llm():
    metric = Faithfulness()
    # FakeLLM returns statement decomposition then NLI verdicts.\n        Result: faithfulness=1.0.
    fake_llm = FakeLLM(
        [json.dumps({'statements': ['Paris is the capital of France']}), json.dumps({'verdicts': [{'verdict': 'yes'}]})]
    )
    result = metric.calculate(
        'Paris is the capital of France',
        llm=fake_llm,
        context=['Paris is the capital city of France.'],
        question='What is the capital of France?',
    )
    assert result['faithfulness'] == 1.0


def test_answercorrectnesswithfakellm_answer_correctness_with_fake_llm():
    metric = AnswerCorrectness()
    # FakeLLM returns decompositions for both answers, then classification.\n        First two calls return statements, third returns TP/FP/FN.\n        Result: answer_correctness=1.0.
    fake_llm = FakeLLM(
        [
            json.dumps({'statements': ['stmt1']}),
            json.dumps({'statements': ['stmt1']}),
            json.dumps({'tp': ['stmt1'], 'fp': [], 'fn': []}),
        ]
    )
    result = metric.calculate(
        'Paris is the capital of France',
        reference='Paris is the capital of France',
        llm=fake_llm,
        question='What is the capital of France?',
    )
    assert result['answer_correctness'] == 1.0
    assert result['answer_tp'] == 1.0
    assert result['answer_fp'] == 0.0
    assert result['answer_fn'] == 0.0


def test_contextprecisionwithfakellm_context_precision_with_fake_llm():
    metric = ContextPrecision()
    # FakeLLM returns verdict='yes' for each context.\n        With 2 contexts both relevant -> AP=1.0.
    fake_llm = FakeLLM([json.dumps({'verdict': 'yes'}), json.dumps({'verdict': 'yes'})])
    result = metric.calculate(
        ['Paris is the capital of France', 'France is in Europe'],
        reference='Paris',
        llm=fake_llm,
        question='What is the capital of France?',
    )
    assert result['context_precision'] == 1.0


def test_contextrelevancywithfakellm_context_relevancy_with_fake_llm():
    metric = ContextRelevancy()
    # Dual-rating: 2 LLM calls per context × 2 contexts = 4 responses
    fake_llm = FakeLLM(
        [json.dumps({'score': 2}), json.dumps({'score': 2}), json.dumps({'score': 2}), json.dumps({'score': 2})]
    )
    result = metric.calculate(
        ['Paris is the capital of France', 'France is in Europe'],
        llm=fake_llm,
        question='What is the capital of France?',
    )
    assert result['context_relevancy'] == 1.0


def test_evidencerecallwithfakellm_evidence_recall_with_fake_llm():
    metric = EvidenceRecallLLM()
    # New batch format: single LLM call returns classifications list (GraphRAG-Benchmark pattern)
    fake_llm = FakeLLM(
        [
            json.dumps(
                {
                    'classifications': [
                        {'statement': 'Paris is the capital of France', 'reason': 'matches', 'attributed': 1}
                    ]
                }
            )
        ]
    )
    result = metric.calculate(
        ['Paris is the capital of France'], reference=['Paris is the capital of France'], llm=fake_llm
    )
    assert result['evidence_recall_llm'] == 1.0
