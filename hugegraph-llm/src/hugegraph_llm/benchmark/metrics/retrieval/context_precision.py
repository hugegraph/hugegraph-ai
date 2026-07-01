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

"""Context precision metric using LLM-based per-context relevance judgment.

Measures how precisely the retrieved contexts address the question
by computing Average Precision over binary relevance judgments.

Reference: RAGAS context_precision.py
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


def _compute_average_precision(relevances: List[int]) -> float:
    """Compute Average Precision from a list of binary relevance labels.

    AP = sum(P@k * rel(k)) / num_relevant
    where P@k = number of relevant items in top-k / k.
    """
    if not relevances:
        return 0.0

    num_relevant = sum(relevances)
    if num_relevant == 0:
        return 0.0

    ap_sum = 0.0
    relevant_so_far = 0
    for k, rel in enumerate(relevances, start=1):
        if rel:
            relevant_so_far += 1
            ap_sum += relevant_so_far / k

    return ap_sum / num_relevant


@MetricRegistry.register
class ContextPrecision(BaseMetric):
    """Context precision via LLM-based relevance + Average Precision.

    Requires ``llm``, ``question``, and ground truth answer as
    ``reference``. Returns None when no LLM is available.

    Registered name: ``context_precision``
    """

    name: str = "context_precision"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate context precision (Average Precision).

        Args:
            prediction: List of retrieved context strings.
            reference: Ground truth answer (str).
            **kwargs: Must contain ``llm`` and ``question``.

        Returns:
            Dict with ``context_precision`` key (float 0-1 or None).
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {"context_precision": None}

        contexts = prediction if isinstance(prediction, list) else []
        question = kwargs.get("question", "")
        if isinstance(reference, list):
            ground_truth = "\n".join(str(item) for item in reference)
        else:
            ground_truth = str(reference or "")
        language = kwargs.get("language", "en")

        if not contexts:
            return {"context_precision": 0.0}

        # Judge each context for relevance
        relevances: List[int] = []
        for ctx in contexts:
            prompt = get_prompt("CONTEXT_PRECISION_PROMPT", language).format(
                question=question,
                ground_truth=ground_truth,
                context=str(ctx),
            )
            try:
                response = retry_llm_call(llm, prompt)
                data = _parse_json_response(response)
                if data:
                    verdict = str(data.get("verdict", "")).strip().lower()
                    relevances.append(1 if verdict == "yes" else 0)
                else:
                    relevances.append(0)
            except Exception as e:
                logger.warning("Context precision judgment failed: %s", e)
                relevances.append(0)

        ap = _compute_average_precision(relevances)
        return {"context_precision": round(ap, 4)}
