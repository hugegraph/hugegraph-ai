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

"""Structural integrity metrics for extracted graphs.

Checks for orphan edges (endpoints missing from vertex set) and
duplicate entities/edges within the extracted graph.
"""

from typing import Any, Dict, List, Set, Tuple

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_answer


def _vertex_key(vertex: Dict[str, Any], language: str = "en") -> Tuple[str, str]:
    """Normalized (label, name) key for deduplication."""
    label = normalize_answer(str(vertex.get("label", "")), language)
    name = vertex.get("name")
    if not name and isinstance(vertex.get("properties"), dict):
        name = vertex["properties"].get("name", "")
    name = normalize_answer(str(name or ""), language)
    return (label, name)


def _edge_key(edge: Dict[str, Any], language: str = "en") -> Tuple[str, str, str]:
    """Normalized (outV, label, inV) key for deduplication."""
    out_v = normalize_answer(str(_edge_out(edge)), language)
    label = normalize_answer(str(edge.get("label", "")), language)
    in_v = normalize_answer(str(_edge_in(edge)), language)
    return (out_v, label, in_v)


@MetricRegistry.register
class StructuralIntegrity(BaseMetric):
    """Structural integrity metrics for an extracted graph.

    Expects prediction as a dict with ``vertices`` and ``edges`` lists.

    Metrics:
    - orphan_edge_rate: fraction of edges whose endpoints are not in vertices
    - duplicate_entity_rate: fraction of duplicate vertices (same label+name)
    - duplicate_edge_rate: fraction of duplicate edges (same triple)

    Registered name: ``structural_integrity``
    """

    name: str = "structural_integrity"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate structural integrity metrics.

        Args:
            prediction: Dict with ``vertices`` (List[Dict]) and
                        ``edges`` (List[Dict]).
            reference: Unused.
            **kwargs: Optional ``language`` ("en" or "zh").

        Returns:
            Dict with orphan_edge_rate, duplicate_entity_rate,
            duplicate_edge_rate.
        """
        if not isinstance(prediction, dict):
            return {
                "orphan_edge_rate": 0.0,
                "duplicate_entity_rate": 0.0,
                "duplicate_edge_rate": 0.0,
            }

        vertices: List[Dict[str, Any]] = prediction.get("vertices", [])
        edges: List[Dict[str, Any]] = prediction.get("edges", [])

        if not isinstance(vertices, list):
            vertices = []
        if not isinstance(edges, list):
            edges = []

        language = kwargs.get("language", "en")

        # --- orphan_edge_rate ---
        vertex_names: Set[str] = set()
        for v in vertices:
            name = v.get("name")
            if not name and isinstance(v.get("properties"), dict):
                name = v["properties"].get("name", "")
            if name:
                vertex_names.add(normalize_answer(str(name), language))

        if edges:
            orphan_count = 0
            for e in edges:
                out_v = normalize_answer(str(_edge_out(e)), language)
                in_v = normalize_answer(str(_edge_in(e)), language)
                if out_v and out_v not in vertex_names:
                    orphan_count += 1
                elif in_v and in_v not in vertex_names:
                    orphan_count += 1
            orphan_edge_rate = orphan_count / len(edges)
        else:
            orphan_edge_rate = 0.0

        # --- duplicate_entity_rate ---
        if vertices:
            seen_entities: Set[Tuple[str, str]] = set()
            dup_entity_count = 0
            for v in vertices:
                key = _vertex_key(v, language)
                if key == ("", ""):
                    continue
                if key in seen_entities:
                    dup_entity_count += 1
                else:
                    seen_entities.add(key)
            duplicate_entity_rate = dup_entity_count / len(vertices)
        else:
            duplicate_entity_rate = 0.0

        # --- duplicate_edge_rate ---
        if edges:
            seen_edges: Set[Tuple[str, str, str]] = set()
            dup_edge_count = 0
            for e in edges:
                key = _edge_key(e, language)
                if key == ("", "", ""):
                    continue
                if key in seen_edges:
                    dup_edge_count += 1
                else:
                    seen_edges.add(key)
            duplicate_edge_rate = dup_edge_count / len(edges)
        else:
            duplicate_edge_rate = 0.0

        return {
            "orphan_edge_rate": round(orphan_edge_rate, 4),
            "duplicate_entity_rate": round(duplicate_entity_rate, 4),
            "duplicate_edge_rate": round(duplicate_edge_rate, 4),
        }
