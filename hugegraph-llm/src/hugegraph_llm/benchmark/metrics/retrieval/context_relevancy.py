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

"""Context relevancy metric using LLM-based graded relevance scoring.

Rates each retrieved context on a 0-2 scale for relevance to the
question, then normalizes the mean score to [0, 1].

Reference: GraphRAG-Bench context_relevance.py
"""

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


_CONTEXT_MAX_CHARS = 20000  # GraphRAG-Benchmark standard truncation limit


def _score_context(llm: Any, question: str, ctx: str, language: str = "en") -> int:
    """Score a single context for relevance (0-2 scale).

    Calls LLM twice and averages (GraphRAG-Benchmark dual-rating pattern)
    to reduce LLM variance.
    """
    prompt = get_prompt("CONTEXT_RELEVANCE_PROMPT", language).format(
        question=question,
        context=str(ctx)[:_CONTEXT_MAX_CHARS],
    )

    scores = []
    for _ in range(2):  # Dual-rating for variance reduction
        try:
            response = retry_llm_call(llm, prompt)
            data = _parse_json_response(response)
            if data and "score" in data:
                score = max(0, min(2, int(data["score"])))
                scores.append(score)
            else:
                scores.append(0)
        except Exception as e:
            logger.warning("Context relevancy scoring failed: %s", e)
            scores.append(0)

    return round(sum(scores) / len(scores))


@MetricRegistry.register
class ContextRelevancy(BaseMetric):
    """Context relevancy via LLM-based graded scoring (0-2).

    Requires ``llm`` and ``question`` in kwargs. Returns None when
    no LLM is available.

    Registered name: ``context_relevancy``
    """

    name: str = "context_relevancy"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate context relevancy score.

        Args:
            prediction: List of retrieved context strings.
            reference: Unused.
            **kwargs: Must contain ``llm`` and ``question``.

        Returns:
            Dict with ``context_relevancy`` key (float 0-1 or None).
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {"context_relevancy": None}

        contexts = prediction if isinstance(prediction, list) else []
        question = kwargs.get("question", "")
        language = kwargs.get("language", "en")

        if not contexts:
            return {"context_relevancy": 0.0}

        scores: List[int] = []
        for ctx in contexts:
            ctx_str = str(ctx)
            # Exact-match guard: context == question is degenerate (GraphRAG-Benchmark)
            if ctx_str.strip() == question.strip() or ctx_str.strip() in question:
                scores.append(0)
                continue
            scores.append(_score_context(llm, question, ctx_str, language))

        # Normalize: mean score / 2 to get 0-1 range
        mean_score = sum(scores) / len(scores)
        relevancy = mean_score / 2.0

        return {"context_relevancy": round(relevancy, 4)}
