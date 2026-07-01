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

"""Triple-level Precision, Recall, and F1 for graph extraction evaluation.

Matches candidate edges against gold edges using normalized
(outV_name, edge_label, inV_name) triples.
"""

from typing import Any, Dict, List, Set, Tuple

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_answer


def _triple_key(edge: Dict[str, Any], language: str = "en") -> Tuple[str, str, str]:
    """Build a normalized (outV_name, label, inV_name) matching key for an edge."""
    out_v = normalize_answer(str(_edge_out(edge)), language)
    label = normalize_answer(str(edge.get("label", "")), language)
    in_v = normalize_answer(str(_edge_in(edge)), language)
    return (out_v, label, in_v)


def _compute_triple_pr_f1(
    prediction: List[Dict[str, Any]],
    reference: List[Dict[str, Any]],
    language: str = "en",
) -> Dict[str, float]:
    """Core computation for triple precision, recall, and F1."""
    if not prediction and not reference:
        return {"triple_precision": 0.0, "triple_recall": 0.0, "triple_f1": 0.0}

    pred_keys: Set[Tuple[str, str, str]] = {_triple_key(e, language) for e in (prediction or [])}
    ref_keys: Set[Tuple[str, str, str]] = {_triple_key(e, language) for e in (reference or [])}

    # Remove degenerate keys
    pred_keys.discard(("", "", ""))
    ref_keys.discard(("", "", ""))

    tp = len(pred_keys & ref_keys)
    precision = tp / len(pred_keys) if pred_keys else 0.0
    recall = tp / len(ref_keys) if ref_keys else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "triple_precision": round(precision, 4),
        "triple_recall": round(recall, 4),
        "triple_f1": round(f1, 4),
    }


@MetricRegistry.register
class TripleF1(BaseMetric):
    """Triple-level F1 (also returns precision and recall).

    Registered name: ``triple_f1``
    """

    name: str = "triple_f1"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate triple precision, recall, and F1.

        Args:
            prediction: List of candidate edge dicts.
            reference: List of gold edge dicts.
            **kwargs: Optional ``language`` ("en" or "zh").

        Returns:
            Dict with triple_precision, triple_recall, triple_f1.
        """
        pred = prediction if isinstance(prediction, list) else []
        ref = reference if isinstance(reference, list) else []
        language = kwargs.get("language", "en")
        return _compute_triple_pr_f1(pred, ref, language)
