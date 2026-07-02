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

"""Property-level Precision, Recall, and F1 for graph extraction evaluation.

First matches entities/edges by their identity key (name or triple),
then compares the ``properties`` dict of matched pairs to compute
property-level scores.
"""

from typing import Any, Dict, List, Tuple

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out, _is_edge
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_answer


def _vertex_identity(vertex: Dict[str, Any], language: str = "en") -> Tuple[str, str]:
    """Return normalized (label, name) identity for a vertex."""
    label = normalize_answer(str(vertex.get("label", "")), language)
    name = vertex.get("name")
    if not name and isinstance(vertex.get("properties"), dict):
        name = vertex["properties"].get("name", "")
    name = normalize_answer(str(name or ""), language)
    return (label, name)


def _edge_identity(edge: Dict[str, Any], language: str = "en") -> Tuple[str, str, str]:
    """Return normalized (outV, label, inV) identity for an edge."""
    out_v = normalize_answer(str(_edge_out(edge)), language)
    label = normalize_answer(str(edge.get("label", "")), language)
    in_v = normalize_answer(str(_edge_in(edge)), language)
    return (out_v, label, in_v)


def _extract_properties(item: Dict[str, Any], language: str = "en") -> Dict[str, str]:
    """Extract and normalize properties dict from a vertex or edge."""
    props = item.get("properties")
    if not isinstance(props, dict):
        return {}
    return {normalize_answer(str(k), language): normalize_answer(str(v), language) for k, v in props.items()}


def _match_and_score_properties(
    prediction: List[Dict[str, Any]],
    reference: List[Dict[str, Any]],
    language: str = "en",
) -> Dict[str, float]:
    """Match items by identity, then compare properties for P/R/F1."""
    if not prediction and not reference:
        return {"property_precision": 0.0, "property_recall": 0.0, "property_f1": 0.0}

    pred_items = prediction or []
    ref_items = reference or []

    # Separate into vertices and edges, build identity -> properties maps
    pred_vertex_props: Dict[Tuple[str, str], Dict[str, str]] = {}
    pred_edge_props: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for item in pred_items:
        props = _extract_properties(item, language)
        if _is_edge(item):
            key = _edge_identity(item, language)
            if key != ("", "", ""):
                pred_edge_props[key] = props
        else:
            key = _vertex_identity(item, language)
            if key != ("", ""):
                pred_vertex_props[key] = props

    ref_vertex_props: Dict[Tuple[str, str], Dict[str, str]] = {}
    ref_edge_props: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for item in ref_items:
        props = _extract_properties(item, language)
        if _is_edge(item):
            key = _edge_identity(item, language)
            if key != ("", "", ""):
                ref_edge_props[key] = props
        else:
            key = _vertex_identity(item, language)
            if key != ("", ""):
                ref_vertex_props[key] = props

    # Collect all matched property pairs
    total_pred_props = 0
    total_ref_props = 0
    matched_props = 0

    # Match vertices
    for key, pred_p in pred_vertex_props.items():
        total_pred_props += len(pred_p)
        if key in ref_vertex_props:
            ref_p = ref_vertex_props[key]
            total_ref_props += len(ref_p)
            for pk, pv in pred_p.items():
                if pk in ref_p and ref_p[pk] == pv:
                    matched_props += 1
        else:
            # No match in reference - still count reference props if they exist
            pass

    # Count unmatched reference vertex props
    for key, ref_p in ref_vertex_props.items():
        if key not in pred_vertex_props:
            total_ref_props += len(ref_p)

    # Match edges
    for key, pred_p in pred_edge_props.items():
        total_pred_props += len(pred_p)
        if key in ref_edge_props:
            ref_p = ref_edge_props[key]
            total_ref_props += len(ref_p)
            for pk, pv in pred_p.items():
                if pk in ref_p and ref_p[pk] == pv:
                    matched_props += 1

    # Count unmatched reference edge props
    for key, ref_p in ref_edge_props.items():
        if key not in pred_edge_props:
            total_ref_props += len(ref_p)

    precision = matched_props / total_pred_props if total_pred_props > 0 else 0.0
    recall = matched_props / total_ref_props if total_ref_props > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "property_precision": round(precision, 4),
        "property_recall": round(recall, 4),
        "property_f1": round(f1, 4),
    }


@MetricRegistry.register
class PropertyF1(BaseMetric):
    """Property-level F1 after entity/edge matching.

    Registered name: ``property_f1``
    """

    name: str = "property_f1"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate property precision, recall, and F1.

        Args:
            prediction: List of vertex/edge dicts with properties.
            reference: List of gold vertex/edge dicts with properties.
            **kwargs: Optional ``language`` ("en" or "zh").

        Returns:
            Dict with property_precision, property_recall, property_f1.
        """
        pred = prediction if isinstance(prediction, list) else []
        ref = reference if isinstance(reference, list) else []
        language = kwargs.get("language", "en")
        return _match_and_score_properties(pred, ref, language)
