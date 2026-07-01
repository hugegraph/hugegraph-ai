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

"""Schema validity metrics for graph extraction evaluation.

Validates extracted graph elements against a provided schema definition,
checking type constraints, required property completeness, and edge
endpoint legality.
"""

from typing import Any, Dict, List, Set

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out, _is_edge
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_answer


def _get_vertex_label_map(items: List[Dict[str, Any]], language: str = "en") -> Dict[str, str]:
    """Build a mapping from normalized vertex name to its label.

    Used to look up endpoint labels when validating edges.
    """
    mapping: Dict[str, str] = {}
    for item in items:
        if not _is_edge(item):
            name = item.get("name")
            if not name and isinstance(item.get("properties"), dict):
                name = item["properties"].get("name", "")
            label = item.get("label", "")
            if name:
                mapping[normalize_answer(str(name), language)] = normalize_answer(str(label), language)
    return mapping


@MetricRegistry.register
class SchemaValidity(BaseMetric):
    """Schema conformance metrics for extracted graph elements.

    Checks three aspects against a provided schema:
    - type_constraint_pass: fraction of vertices whose label exists in schema
    - required_property_fill: fraction of vertices with all primary_keys present
    - illegal_edge_rate: fraction of edges whose endpoint labels violate schema

    Registered name: ``schema_validity``
    """

    name: str = "schema_validity"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate schema validity metrics.

        Args:
            prediction: List of vertex and edge dicts.
            reference: Unused (schema validation is prediction-only).
            **kwargs: Must contain ``schema`` dict with ``vertexlabels``
                      and ``edgelabels`` lists. Optional ``language``.

        Returns:
            Dict with type_constraint_pass, required_property_fill,
            illegal_edge_rate.
        """
        items = prediction if isinstance(prediction, list) else []
        schema = kwargs.get("schema")
        language = kwargs.get("language", "en")

        if not items or not isinstance(schema, dict):
            return {
                "type_constraint_pass": 0.0,
                "required_property_fill": 0.0,
                "illegal_edge_rate": 0.0,
            }

        # Parse schema
        vertex_labels_schema: Dict[str, Dict[str, Any]] = {}
        for vl in schema.get("vertexlabels", []):
            vl_name = normalize_answer(str(vl.get("name", "")), language)
            if vl_name:
                vertex_labels_schema[vl_name] = vl

        edge_labels_schema: Dict[str, Dict[str, Any]] = {}
        for el in schema.get("edgelabels", []):
            el_name = normalize_answer(str(el.get("name", "")), language)
            if el_name:
                edge_labels_schema[el_name] = el

        valid_vl_names: Set[str] = set(vertex_labels_schema.keys())

        # Build vertex name -> label map for edge endpoint lookup
        vertex_name_to_label = _get_vertex_label_map(items, language)

        # --- type_constraint_pass ---
        vertices = [item for item in items if not _is_edge(item)]
        if vertices:
            type_pass_count = sum(
                1 for v in vertices if normalize_answer(str(v.get("label", "")), language) in valid_vl_names
            )
            type_constraint_pass = type_pass_count / len(vertices)
        else:
            type_constraint_pass = 0.0

        # --- required_property_fill ---
        if vertices:
            fill_count = 0
            for v in vertices:
                vl_name = normalize_answer(str(v.get("label", "")), language)
                if vl_name not in vertex_labels_schema:
                    continue
                primary_keys = vertex_labels_schema[vl_name].get("primary_keys", [])
                if not primary_keys:
                    fill_count += 1
                    continue
                props = v.get("properties", {})
                if not isinstance(props, dict):
                    props = {}
                # Check all primary keys are present and non-empty
                all_present = all(
                    str(pk) in props and props[str(pk)] is not None and str(props[str(pk)]).strip() != ""
                    for pk in primary_keys
                )
                if all_present:
                    fill_count += 1
            required_property_fill = fill_count / len(vertices)
        else:
            required_property_fill = 0.0

        # --- illegal_edge_rate ---
        edges = [item for item in items if _is_edge(item)]
        if edges:
            illegal_count = 0
            for e in edges:
                edge_label = normalize_answer(str(e.get("label", "")), language)
                # Check if edge label is defined in schema
                if edge_label not in edge_labels_schema:
                    illegal_count += 1
                    continue
                el_schema = edge_labels_schema[edge_label]
                src_label = normalize_answer(str(el_schema.get("source_label", "")), language)
                dst_label = normalize_answer(str(el_schema.get("target_label", "")), language)

                # Look up actual endpoint labels
                out_v_name = normalize_answer(str(_edge_out(e)), language)
                in_v_name = normalize_answer(str(_edge_in(e)), language)
                actual_src = vertex_name_to_label.get(out_v_name, "")
                actual_dst = vertex_name_to_label.get(in_v_name, "")

                # If we can resolve endpoint labels, check them
                if actual_src and src_label and actual_src != src_label:
                    illegal_count += 1
                elif actual_dst and dst_label and actual_dst != dst_label:
                    illegal_count += 1
            illegal_edge_rate = illegal_count / len(edges)
        else:
            illegal_edge_rate = 0.0

        return {
            "type_constraint_pass": round(type_constraint_pass, 4),
            "required_property_fill": round(required_property_fill, 4),
            "illegal_edge_rate": round(illegal_edge_rate, 4),
        }
