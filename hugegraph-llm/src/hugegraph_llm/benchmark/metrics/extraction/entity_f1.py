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

"""Entity-level Precision, Recall, and F1 for graph extraction evaluation.

Matches candidate vertices against gold vertices using normalized
(label, name) tuples. Each vertex dict is expected to have at least
`label` and one of `name` / `properties.name` fields.
"""

from typing import Any, Dict, List, Set, Tuple

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_answer


def _entity_key(vertex: Dict[str, Any], language: str = "en") -> Tuple[str, str]:
    """Build a normalized (label, name) matching key for a vertex."""
    label = normalize_answer(str(vertex.get("label", "")), language)
    # Try 'name' first, then fall back to properties.name
    name = vertex.get("name")
    if not name and isinstance(vertex.get("properties"), dict):
        name = vertex["properties"].get("name", "")
    name = normalize_answer(str(name or ""), language)
    return (label, name)


def _compute_entity_pr_f1(
    prediction: List[Dict[str, Any]],
    reference: List[Dict[str, Any]],
    language: str = "en",
) -> Dict[str, float]:
    """Core computation shared by EntityPrecision / EntityRecall / EntityF1."""
    if not prediction and not reference:
        return {"entity_precision": 0.0, "entity_recall": 0.0, "entity_f1": 0.0}

    pred_keys: Set[Tuple[str, str]] = {_entity_key(v, language) for v in (prediction or [])}
    ref_keys: Set[Tuple[str, str]] = {_entity_key(v, language) for v in (reference or [])}

    # Remove empty keys that arise from malformed vertices
    pred_keys.discard(("", ""))
    ref_keys.discard(("", ""))

    tp = len(pred_keys & ref_keys)
    precision = tp / len(pred_keys) if pred_keys else 0.0
    recall = tp / len(ref_keys) if ref_keys else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "entity_precision": round(precision, 4),
        "entity_recall": round(recall, 4),
        "entity_f1": round(f1, 4),
    }


@MetricRegistry.register
class EntityF1(BaseMetric):
    """Entity-level F1 (also returns precision and recall).

    Registered name: ``entity_f1``
    """

    name: str = "entity_f1"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate entity precision, recall, and F1.

        Args:
            prediction: List of candidate vertex dicts.
            reference: List of gold vertex dicts.
            **kwargs: Optional ``language`` ("en" or "zh").

        Returns:
            Dict with entity_precision, entity_recall, entity_f1.
        """
        pred = prediction if isinstance(prediction, list) else []
        ref = reference if isinstance(reference, list) else []
        language = kwargs.get("language", "en")
        return _compute_entity_pr_f1(pred, ref, language)
