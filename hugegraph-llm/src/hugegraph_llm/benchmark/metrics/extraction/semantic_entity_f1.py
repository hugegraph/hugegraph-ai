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

"""Semantic entity F1 via LLM-based semantic matching.

Unlike :class:`EntityF1` which uses exact (label, name) matching, this metric
uses an LLM judge to determine whether candidate entities are *semantically*
equivalent to gold entities — allowing for synonym normalization, abbreviation
expansion, and phrasing variation (e.g. "制动液" ↔ "制动液检查/更换").

Reference: car33 评分规则.md §4.1 (entity normalization rules),
ragas ContextEntityRecall (LLM entity extraction pattern).
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

# Max vertices to send per side in a single LLM call (trimmed for cost control)
_MAX_VERTICES_PER_SIDE = 80


def _format_vertices(vertices: List[Dict[str, Any]], language: str = "en") -> List[str]:
    """Format vertices as indexed string lines for the prompt."""
    lines = []
    for i, v in enumerate(vertices[: _MAX_VERTICES_PER_SIDE]):
        label = v.get("label", "")
        name = v.get("name")
        if not name and isinstance(v.get("properties"), dict):
            name = v["properties"].get("name", "")
        name = str(name or "")
        lines.append(f"[{i}] {{\"label\": \"{label}\", \"name\": \"{name}\"}}")
    return lines


def _compute_semantic_entity_pr_f1(
    llm: Any,
    prediction: List[Dict[str, Any]],
    reference: List[Dict[str, Any]],
    language: str = "en",
) -> Dict[str, Optional[float]]:
    """Core: call LLM to match entities, then compute precision/recall/F1.

    Returns None values when no LLM is available.
    """
    if llm is None:
        return {
            "semantic_entity_precision": None,
            "semantic_entity_recall": None,
            "semantic_entity_f1": None,
            "semantic_entity_matched": None,
        }

    if not prediction and not reference:
        return {
            "semantic_entity_precision": 0.0,
            "semantic_entity_recall": 0.0,
            "semantic_entity_f1": 0.0,
            "semantic_entity_matched": 0,
        }

    gold_lines = _format_vertices(reference, language)
    cand_lines = _format_vertices(prediction, language)

    if not cand_lines or not gold_lines:
        return {
            "semantic_entity_precision": 0.0,
            "semantic_entity_recall": 0.0,
            "semantic_entity_f1": 0.0,
            "semantic_entity_matched": 0,
        }

    prompt = get_prompt("ENTITY_SEMANTIC_MATCH_PROMPT", language).format(
        gold_entities="\n".join(gold_lines),
        candidate_entities="\n".join(cand_lines),
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
        logger.warning("Semantic entity matching failed: %s", e)

    gold_count = len(gold_lines)
    cand_count = len(cand_lines)
    matched = len(matches)

    precision = matched / cand_count if cand_count > 0 else 0.0
    recall = matched / gold_count if gold_count > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "semantic_entity_precision": round(precision, 4),
        "semantic_entity_recall": round(recall, 4),
        "semantic_entity_f1": round(f1, 4),
        "semantic_entity_matched": matched,
    }


@MetricRegistry.register
class SemanticEntityF1(BaseMetric):
    """Entity-level F1 using LLM-based semantic matching.

    Unlike :class:`EntityF1` (exact string match), this metric asks an LLM
    judge to determine semantic equivalence between candidate and gold
    entities, allowing synonym normalization, abbreviation expansion, and
    phrasing variation.

    Requires ``llm`` in kwargs. Returns ``None`` for all scores when no
    LLM is available (offline mode).

    Registered name: ``semantic_entity_f1``
    """

    name: str = "semantic_entity_f1"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate semantic entity precision, recall, and F1.

        Args:
            prediction: List of candidate vertex dicts.
            reference: List of gold vertex dicts.
            **kwargs: Must contain ``llm``. Optional ``language`` ("en" or "zh").

        Returns:
            Dict with semantic_entity_precision, semantic_entity_recall,
            semantic_entity_f1, semantic_entity_matched.
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {
                "semantic_entity_precision": None,
                "semantic_entity_recall": None,
                "semantic_entity_f1": None,
                "semantic_entity_matched": None,
            }

        pred = prediction if isinstance(prediction, list) else []
        ref = reference if isinstance(reference, list) else []
        language = kwargs.get("language", "en")
        return _compute_semantic_entity_pr_f1(llm, pred, ref, language)
