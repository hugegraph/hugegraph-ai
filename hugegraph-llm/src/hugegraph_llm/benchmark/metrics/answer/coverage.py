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

"""Coverage score metric: what fraction of reference facts appear in the response.

Two-step LLM pipeline (mirrors GraphRAG-Benchmark coverage_score):
1. Extract atomic, independently-verifiable facts from the reference answer.
2. For each fact, judge whether it is covered by the response (attributed 1/0).

Score = (#covered facts) / (#reference facts).

This complements :class:`AnswerCorrectness` (bidirectional TP/FP/FN) with a
reference-anchored recall of factual content — the standard generation metric
for Contextual Summarization / Creative Generation tasks in GraphRAG-Benchmark.

Reference: GraphRAG-Benchmark (ICLR'26) ``Evaluation/metrics/coverage.py``.
"""

import json
import logging
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

# Cap each input to avoid oversized prompts (GraphRAG-Bench uses 3000 chars).
_MAX_CHARS = 3000


def _extract_facts(llm: Any, question: str, reference: str, language: str = "en") -> List[str]:
    """Extract atomic, independently-verifiable facts from the reference answer."""
    prompt = get_prompt("COVERAGE_FACT_EXTRACT_PROMPT", language).format(
        question=question, reference=reference[:_MAX_CHARS]
    )
    try:
        response = retry_llm_call(llm, prompt)
        data = _parse_json_response(response)
        if data and isinstance(data.get("facts"), list):
            return [str(f).strip() for f in data["facts"] if str(f).strip()]
    except Exception as e:
        logger.warning("Coverage fact extraction failed: %s", e)
    return []


def _check_coverage(
    llm: Any,
    question: str,
    facts: List[str],
    response: str,
    language: str = "en",
) -> List[Dict[str, int]]:
    """Judge each reference fact as covered (1) or not (0) in the response."""
    prompt = get_prompt("COVERAGE_CHECK_PROMPT", language).format(
        question=question,
        response=response[:_MAX_CHARS],
        facts=json.dumps(facts, ensure_ascii=False),
    )
    try:
        resp = retry_llm_call(llm, prompt)
        data = _parse_json_response(resp)
        if data and isinstance(data.get("classifications"), list):
            valid: List[Dict[str, int]] = []
            for item in data["classifications"]:
                if not isinstance(item, dict):
                    continue
                attr = item.get("attributed")
                if attr in (0, 1, "0", "1"):
                    valid.append(
                        {
                            "statement": str(item.get("statement", "")),
                            "attributed": int(attr),
                        }
                    )
            return valid
    except Exception as e:
        logger.warning("Coverage check failed: %s", e)
    return []


@MetricRegistry.register
class Coverage(BaseMetric):
    """Coverage score: fraction of reference facts covered by the response.

    Requires ``llm`` and ``question`` in kwargs.

    Unlike :class:`AnswerCorrectness` (which decomposes both answers and
    classifies TP/FP/FN), coverage only decomposes the *reference* and checks
    each fact against the *response* — i.e. it measures factual recall of the
    gold answer, not precision. This makes it the right metric for open-ended /
    summarization tasks where a longer response is acceptable as long as it
    covers the key facts.

    Registered name: ``coverage``.
    """

    name: str = "coverage"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate coverage.

        Args:
            prediction: Candidate answer text (str).
            reference: Gold answer text (str).
            **kwargs: Must contain ``llm`` and ``question``.

        Returns:
            Dict with ``coverage`` (0..1, or None when LLM unavailable /
            fact extraction fails) plus ``coverage_ref_facts`` and
            ``coverage_covered`` for transparency.
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {
                "coverage": None,
                "coverage_ref_facts": None,
                "coverage_covered": None,
            }

        question = kwargs.get("question", "")
        response = str(prediction or "")
        gold = str(reference or "")
        language = kwargs.get("language", "en")

        # GraphRAG-Bench convention: empty reference = perfect coverage (vacuous).
        if not gold.strip():
            return {"coverage": 1.0, "coverage_ref_facts": 0, "coverage_covered": 0}

        facts = _extract_facts(llm, question, gold, language)
        if not facts:
            return {"coverage": None, "coverage_ref_facts": 0, "coverage_covered": 0}

        judgments = _check_coverage(llm, question, facts, response, language)
        covered = sum(j["attributed"] for j in judgments)
        total = len(facts)
        score = covered / total if total else 0.0

        return {
            "coverage": round(score, 4),
            "coverage_ref_facts": total,
            "coverage_covered": covered,
        }
