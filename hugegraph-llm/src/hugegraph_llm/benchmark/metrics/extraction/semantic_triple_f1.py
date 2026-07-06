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

"""Semantic triple F1 via LLM-based semantic matching.

Unlike :class:`TripleF1` which uses exact normalized (outV, label, inV)
matching, this metric uses an LLM judge to determine whether candidate triples
are *semantically* equivalent to gold triples — checking that source entity,
relation type, target entity, and direction are all semantically aligned.

Reference: car33 评分规则.md §4.2 (relation normalization rules),
ragas NLIStatementPrompt (per-statement entailment judgment).
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
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry

logger = logging.getLogger(__name__)

# Max edges to send per side in a single LLM call
_MAX_EDGES_PER_SIDE = 80


def _format_triples(edges: List[Dict[str, Any]]) -> List[str]:
    """Format edges as indexed triple strings for the prompt."""
    lines = []
    for i, e in enumerate(edges[: _MAX_EDGES_PER_SIDE]):
        out_v = str(_edge_out(e) or "?")
        label = str(e.get("label", "") or "?")
        in_v = str(_edge_in(e) or "?")
        lines.append(f"[{i}] [{out_v}] --{label}--> [{in_v}]")
    return lines


def _compute_semantic_triple_pr_f1(
    llm: Any,
    prediction: List[Dict[str, Any]],
    reference: List[Dict[str, Any]],
    language: str = "en",
) -> Dict[str, Optional[float]]:
    """Core: call LLM to match triples, then compute precision/recall/F1."""
    if llm is None:
        return {
            "semantic_triple_precision": None,
            "semantic_triple_recall": None,
            "semantic_triple_f1": None,
            "semantic_triple_matched": None,
        }

    if not prediction and not reference:
        return {
            "semantic_triple_precision": 0.0,
            "semantic_triple_recall": 0.0,
            "semantic_triple_f1": 0.0,
            "semantic_triple_matched": 0,
        }

    gold_lines = _format_triples(reference)
    cand_lines = _format_triples(prediction)

    if not cand_lines or not gold_lines:
        return {
            "semantic_triple_precision": 0.0,
            "semantic_triple_recall": 0.0,
            "semantic_triple_f1": 0.0,
            "semantic_triple_matched": 0,
        }

    prompt = get_prompt("TRIPLE_SEMANTIC_MATCH_PROMPT", language).format(
        gold_triples="\n".join(gold_lines),
        candidate_triples="\n".join(cand_lines),
    )

    matches: List[List[int]] = []
    try:
        response = retry_llm_call(llm, prompt)
        data = _parse_json_response(response)
        if data and isinstance(data.get("matches"), list):
            matches = [
                m for m in data["matches"]
                if isinstance(m, list) and len(m) == 2
            ]
    except Exception as e:
        logger.warning("Semantic triple matching failed: %s", e)

    gold_count = len(gold_lines)
    cand_count = len(cand_lines)
    matched = len(matches)

    precision = matched / cand_count if cand_count > 0 else 0.0
    recall = matched / gold_count if gold_count > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "semantic_triple_precision": round(precision, 4),
        "semantic_triple_recall": round(recall, 4),
        "semantic_triple_f1": round(f1, 4),
        "semantic_triple_matched": matched,
    }


@MetricRegistry.register
class SemanticTripleF1(BaseMetric):
    """Triple-level F1 using LLM-based semantic matching.

    Unlike :class:`TripleF1` (exact normalized match), this metric asks an LLM
    judge to determine semantic equivalence between candidate and gold triples,
    verifying that source entity, relation type, target entity, and direction
    are all semantically aligned.

    Requires ``llm`` in kwargs. Returns ``None`` for all scores when no
    LLM is available (offline mode).

    Registered name: ``semantic_triple_f1``
    """

    name: str = "semantic_triple_f1"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate semantic triple precision, recall, and F1.

        Args:
            prediction: List of candidate edge dicts.
            reference: List of gold edge dicts.
            **kwargs: Must contain ``llm``. Optional ``language`` ("en" or "zh").

        Returns:
            Dict with semantic_triple_precision, semantic_triple_recall,
            semantic_triple_f1, semantic_triple_matched.
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {
                "semantic_triple_precision": None,
                "semantic_triple_recall": None,
                "semantic_triple_f1": None,
                "semantic_triple_matched": None,
            }

        pred = prediction if isinstance(prediction, list) else []
        ref = reference if isinstance(reference, list) else []
        language = kwargs.get("language", "en")
        return _compute_semantic_triple_pr_f1(llm, pred, ref, language)
