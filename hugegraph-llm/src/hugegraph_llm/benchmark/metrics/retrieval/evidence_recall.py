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

"""Evidence recall metric using LLM-based support verification.

For each gold evidence statement, determines whether it is supported
by any of the retrieved context passages.

Reference: GraphRAG-Bench evidence_recall.py
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

_CONTEXT_MAX_CHARS = 20000


def _validate_classifications(classifications: List) -> List[Dict]:
    """Validate classifications have required fields (GraphRAG-Benchmark pattern)."""
    valid = []
    for item in classifications:
        try:
            if isinstance(item, dict) and "statement" in item and "attributed" in item and item["attributed"] in {0, 1}:
                valid.append(
                    {
                        "statement": str(item["statement"]),
                        "reason": str(item.get("reason", "")),
                        "attributed": int(item["attributed"]),
                    }
                )
        except (TypeError, ValueError):
            continue
    return valid


@MetricRegistry.register
class EvidenceRecallLLM(BaseMetric):
    """Evidence recall via LLM-based gold evidence support check.

    Requires ``llm`` in kwargs. Returns None when no LLM is available.
    Uses GraphRAG-Benchmark batch classification pattern: single LLM call
    evaluates all evidence statements against merged contexts.

    Registered name: ``evidence_recall_llm``
    """

    name: str = "evidence_recall_llm"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate evidence recall score.

        Args:
            prediction: List of retrieved context strings.
            reference: List of gold evidence statements (List[str]).
            **kwargs: Must contain ``llm``.

        Returns:
            Dict with ``evidence_recall_llm`` key (float 0-1 or None).
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {"evidence_recall_llm": None}

        contexts = prediction if isinstance(prediction, list) else []
        gold_evidences = reference if isinstance(reference, list) else []
        language = kwargs.get("language", "en")

        if not gold_evidences:
            # Vacuous truth: no evidence to check → all trivially recalled
            return {"evidence_recall_llm": 1.0}

        if not contexts or not any(c.strip() for c in contexts):
            return {"evidence_recall_llm": 0.0}

        # Merge contexts (GraphRAG-Benchmark: single call with all evidence)
        ctx_text = "\n".join(str(c) for c in contexts)

        prompt = get_prompt("EVIDENCE_RECALL_PROMPT", language).format(
            question=kwargs.get("question", ""),
            context=ctx_text[:_CONTEXT_MAX_CHARS],
            evidence=gold_evidences,
        )

        try:
            response = retry_llm_call(llm, prompt)
            data = _parse_json_response(response)
            if data and "classifications" in data:
                classifications = _validate_classifications(data["classifications"])
                if classifications:
                    attributed = sum(1 for c in classifications if c["attributed"] == 1)
                    score = attributed / len(classifications)
                    return {"evidence_recall_llm": round(score, 4)}
        except Exception as e:
            logger.warning("Evidence recall evaluation failed: %s", e)

        return {"evidence_recall_llm": 0.0}
