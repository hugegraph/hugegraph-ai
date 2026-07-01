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

"""Conflict detection metrics for extracted graphs.

Detects contradictory claims within the extracted knowledge graph:
1. Same entity with conflicting property values for the same key.
2. Symmetric relation conflicts: (A, REL, B) and (B, REL, A) both present
   where REL is not inherently symmetric.
"""

from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_answer

# Relations that are inherently symmetric (no conflict if reversed)
_SYMMETRIC_RELATIONS = frozenset(
    {
        "relatedto",
        "associatedwith",
        "connectedto",
        "similarto",
        "friendof",
        "peerof",
        "siblingof",
        "spouseof",
        "marriedto",
        "partnerof",
        "neighborof",
        "colleagueof",
    }
)


def _get_vertex_name(vertex: Dict[str, Any], language: str = "en") -> str:
    """Extract normalized name from a vertex dict."""
    name = vertex.get("name")
    if not name and isinstance(vertex.get("properties"), dict):
        name = vertex["properties"].get("name", "")
    return normalize_answer(str(name or ""), language)


def _detect_property_conflicts(vertices: List[Dict[str, Any]], language: str = "en") -> int:
    """Count entities with conflicting property values for the same key.

    A conflict occurs when the same (entity_name, property_key) pair has
    multiple distinct values across different vertex entries.
    """
    # Map: (entity_name, prop_key) -> set of values
    prop_map: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    for v in vertices:
        entity_name = _get_vertex_name(v, language)
        if not entity_name:
            continue

        props = v.get("properties")
        if not isinstance(props, dict):
            continue

        for key, value in props.items():
            if key == "name":
                continue  # Skip the name property itself
            norm_key = normalize_answer(str(key), language)
            norm_val = normalize_answer(str(value), language)
            if norm_key and norm_val:
                prop_map[(entity_name, norm_key)].add(norm_val)

    # Count properties with more than one distinct value
    conflicts = sum(1 for values in prop_map.values() if len(values) > 1)
    return conflicts


def _detect_relation_conflicts(edges: List[Dict[str, Any]], language: str = "en") -> int:
    """Count symmetric relation conflicts.

    A conflict occurs when both (A, REL, B) and (B, REL, A) exist and
    REL is not an inherently symmetric relation.
    """
    edge_set: Set[Tuple[str, str, str]] = set()
    for e in edges:
        out_v = normalize_answer(str(_edge_out(e)), language)
        label = normalize_answer(str(e.get("label", "") or ""), language)
        in_v = normalize_answer(str(_edge_in(e)), language)
        if out_v and label and in_v:
            edge_set.add((out_v, label, in_v))

    seen_pairs: Set[frozenset] = set()
    conflicts = 0

    for out_v, label, in_v in edge_set:
        # Skip symmetric relations
        if label in _SYMMETRIC_RELATIONS:
            continue

        pair_key = frozenset([(out_v, in_v), (in_v, out_v)])
        if pair_key in seen_pairs:
            continue

        # Check if reverse edge exists
        if (in_v, label, out_v) in edge_set:
            conflicts += 1
            seen_pairs.add(pair_key)

    return conflicts


@MetricRegistry.register
class ConflictDetection(BaseMetric):
    """Detects contradictory claims in extracted graphs.

    Expects prediction as a dict with ``vertices`` and ``edges`` lists.

    Metrics:
    - conflict_rate: Number of conflicts / total declarations
    - num_conflicts: Total number of detected conflicts

    Registered name: ``conflict_detection``
    """

    name: str = "conflict_detection"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate conflict detection metrics.

        Args:
            prediction: Dict with ``vertices`` and ``edges`` lists.
            reference: Unused.
            **kwargs: Optional ``language`` ("en" or "zh").

        Returns:
            Dict with conflict_rate and num_conflicts.
        """
        if not isinstance(prediction, dict):
            return {"conflict_rate": 0.0, "num_conflicts": 0.0}

        vertices: List[Dict[str, Any]] = prediction.get("vertices", [])
        edges: List[Dict[str, Any]] = prediction.get("edges", [])

        if not isinstance(vertices, list):
            vertices = []
        if not isinstance(edges, list):
            edges = []

        language = kwargs.get("language", "en")
        prop_conflicts = _detect_property_conflicts(vertices, language)
        rel_conflicts = _detect_relation_conflicts(edges, language)
        total_conflicts = prop_conflicts + rel_conflicts

        # Total declarations = unique property assignments + unique edges
        total_declarations = len(edges)
        for v in vertices:
            props = v.get("properties")
            if isinstance(props, dict):
                # Exclude 'name' from declaration count
                total_declarations += max(0, len(props) - (1 if "name" in props else 0))

        if total_declarations == 0:
            conflict_rate = 0.0
        else:
            conflict_rate = total_conflicts / total_declarations

        return {
            "conflict_rate": round(conflict_rate, 4),
            "num_conflicts": float(total_conflicts),
        }
