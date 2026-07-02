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

"""Answer correctness metric using LLM-based statement classification.

Compares candidate answer against reference answer by:
1. Decomposing both answers into atomic statements.
2. Classifying each as TP / FP / FN via LLM.
3. Computing F1 = 2*TP / (2*TP + FP + FN).
4. (Optional) Weighting with semantic similarity (RAGAS / GraphRAG-Bench standard).

Reference: RAGAS answer_correctness, GraphRAG-Bench answer_accuracy.
"""

import logging
import math
from typing import Any, Dict, List, Optional

from hugegraph_llm.benchmark.llm_judge.judge_utils import (
    parse_json_response as _parse_json_response,
)
from hugegraph_llm.benchmark.llm_judge.judge_utils import (
    retry_llm_call,
)
from hugegraph_llm.benchmark.llm_judge.prompts import get_prompt
from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry

logger = logging.getLogger(__name__)

# RAGAS / GraphRAG-Bench standard weights: 75% factuality, 25% semantic similarity
_DEFAULT_WEIGHTS = (0.75, 0.25)


def _decompose_statements(llm: Any, question: str, answer: str, language: str = "en") -> List[str]:
    """Decompose an answer into atomic statements using LLM."""
    prompt = get_prompt("STATEMENT_DECOMPOSE_PROMPT", language).format(question=question, answer=answer)
    try:
        response = retry_llm_call(llm, prompt)
        data = _parse_json_response(response)
        if data and isinstance(data.get("statements"), list):
            return [str(s) for s in data["statements"] if s]
    except Exception as e:
        logger.warning("Statement decomposition failed: %s", e)

    return [answer] if answer else []


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


@MetricRegistry.register
class AnswerCorrectness(BaseMetric):
    """Answer correctness via LLM-based TP/FP/FN classification + optional semantic similarity.

    Requires ``llm`` and ``question`` in kwargs. Optionally accepts
    ``embeddings`` (an object with ``embed_query(text) -> List[float]``)
    for semantic similarity scoring (RAGAS / GraphRAG-Bench standard).

    When embeddings is available: score = 0.75 * F1 + 0.25 * cosine_sim
    When embeddings is None:     score = F1 (factuality only)

    Registered name: ``answer_correctness``
    """

    name: str = "answer_correctness"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate answer correctness.

        Args:
            prediction: Candidate answer text (str).
            reference: Gold answer text (str).
            **kwargs: Must contain ``llm`` and ``question``.
                     Optional: ``embeddings`` for semantic similarity.

        Returns:
            Dict with answer_correctness, answer_tp, answer_fp, answer_fn.
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {
                "answer_correctness": None,
                "answer_tp": None,
                "answer_fp": None,
                "answer_fn": None,
            }

        question = kwargs.get("question", "")
        answer = str(prediction or "")
        gold = str(reference or "")
        embeddings = kwargs.get("embeddings")
        language = kwargs.get("language", "en")

        # Decompose both answers
        cand_stmts = _decompose_statements(llm, question, answer, language)
        ref_stmts = _decompose_statements(llm, question, gold, language)

        if not cand_stmts and not ref_stmts:
            return {
                "answer_correctness": 1.0,
                "answer_tp": 0.0,
                "answer_fp": 0.0,
                "answer_fn": 0.0,
            }

        cand_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(cand_stmts))
        ref_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(ref_stmts))

        prompt = get_prompt("CORRECTNESS_CLASSIFY_PROMPT", language).format(
            question=question,
            candidate_statements=cand_text,
            reference_statements=ref_text,
        )

        tp, fp, fn = 0, 0, 0
        try:
            response = retry_llm_call(llm, prompt)
            data = _parse_json_response(response)
            if data:
                tp = len(data.get("tp", []))
                fp = len(data.get("fp", []))
                fn = len(data.get("fn", []))
        except Exception as e:
            logger.warning("Correctness classification failed: %s", e)

        # F1 = 2*TP / (2*TP + FP + FN)
        denominator = 2 * tp + fp + fn
        f1 = (2 * tp / denominator) if denominator > 0 else 0.0

        # Semantic similarity (RAGAS / GraphRAG-Bench standard)
        sim_score = None
        if embeddings is not None:
            try:
                vec_answer = embeddings.embed_query(answer)
                vec_reference = embeddings.embed_query(gold)
                sim_score = _cosine_similarity(vec_answer, vec_reference)
            except Exception as e:
                logger.warning("Semantic similarity computation failed: %s", e)

        if sim_score is not None:
            # RAGAS / GraphRAG-Bench: weighted average
            score = _DEFAULT_WEIGHTS[0] * f1 + _DEFAULT_WEIGHTS[1] * sim_score
        else:
            score = f1

        return {
            "answer_correctness": round(score, 4),
            "answer_tp": float(tp),
            "answer_fp": float(fp),
            "answer_fn": float(fn),
        }
