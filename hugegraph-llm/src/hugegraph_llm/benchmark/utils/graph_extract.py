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

"""Utilities for adapting HugeGraph-LLM pipeline output to benchmark inputs."""

import json
import re
from typing import Any, Dict, List, Optional, Union


_GRAPH_ID_PREFIX_RE = re.compile(r"^\d+:")


def _strip_graph_id_prefix(value: str) -> str:
    """Remove the numeric label-id prefix used by PropertyGraphExtract.

    PropertyGraphExtract normalizes vertex IDs to ``'<label_id>:<primary_key>'``
    (e.g. ``'1:Alice'`` or ``'1:Alice!Bob'`` for composite keys). This strips
    the leading ``'<label_id>:'`` and returns the primary-key portion.
    """
    return _GRAPH_ID_PREFIX_RE.sub("", str(value))


def _vertex_name(vertex: Dict[str, Any]) -> str:
    """Return a human-readable name for a vertex.

    Prefers ``properties.<primary_key>`` / ``properties.name``, falls back to
    the top-level ``name`` field, then tries to parse the ``id``.
    """
    properties = vertex.get("properties") or {}
    if isinstance(properties, dict):
        # PropertyGraphExtract puts the primary key value(s) inside properties.
        # If the schema uses 'name' as a property, use it directly.
        if "name" in properties:
            return str(properties["name"])
        # Otherwise take the first property value as the display name.
        for value in properties.values():
            if value is not None:
                return str(value)
    if "name" in vertex:
        return str(vertex["name"])
    vertex_id = vertex.get("id")
    if vertex_id is not None:
        return _strip_graph_id_prefix(str(vertex_id))
    return ""


def _build_id_to_name_map(vertices: List[Dict[str, Any]]) -> Dict[str, str]:
    """Map vertex IDs (and names) to display names."""
    mapping: Dict[str, str] = {}
    for vertex in vertices:
        name = _vertex_name(vertex)
        vertex_id = vertex.get("id")
        if vertex_id is not None:
            mapping[str(vertex_id)] = name
        if name:
            mapping[name] = name
    return mapping


def _resolve_endpoint(raw_endpoint: Any, id_to_name: Dict[str, str]) -> str:
    """Convert an edge endpoint (ID or name) to a display name."""
    key = str(raw_endpoint)
    if key in id_to_name:
        return id_to_name[key]
    # Triples mode uses IDs like "person-Alice"; try stripping a "label-" prefix.
    if "-" in key:
        possible_name = key.split("-", 1)[1]
        if possible_name in id_to_name:
            return id_to_name[possible_name]
        return possible_name
    return _strip_graph_id_prefix(key)


def normalize_graph_extract(
    graph_data: Union[str, Dict[str, Any]],
    extract_type: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Convert HugeGraph-LLM ``GraphExtractFlow`` output into benchmark format.

    Supports both ``property_graph`` (``PropertyGraphExtract``) and ``triples``
    (``InfoExtract``) modes, normalizing vertex IDs and edge endpoint fields so
    that the result can be used as ``candidate_vertices`` / ``candidate_edges``
    in benchmark extraction inputs.

    Args:
        graph_data: Either a JSON string or a dict with ``vertices`` / ``edges``.
        extract_type: Optional hint (``"property_graph"`` or ``"triples"``).
            If omitted, the function auto-detects from edge field names.

    Returns:
        ``{"candidate_vertices": [...], "candidate_edges": [...]}``.

    Example:
        >>> data = {
        ...     "vertices": [
        ...         {"id": "1:Alice", "label": "person", "type": "vertex",
        ...          "properties": {"name": "Alice"}},
        ...     ],
        ...     "edges": [
        ...         {"label": "knows", "type": "edge",
        ...          "outV": "1:Alice", "outVLabel": "person",
        ...          "inV": "1:Bob", "inVLabel": "person",
        ...          "properties": {}},
        ...     ],
        ... }
        >>> normalize_graph_extract(data)
        {
            "candidate_vertices": [
                {"label": "person", "name": "Alice", "properties": {"name": "Alice"}},
            ],
            "candidate_edges": [
                {"label": "knows", "outV": "Alice", "inV": "Bob", "properties": {}},
            ],
        }
    """
    if isinstance(graph_data, str):
        graph_data = json.loads(graph_data)
    if not isinstance(graph_data, dict):
        raise TypeError(f"graph_data must be a dict or JSON string, got {type(graph_data).__name__}")

    vertices = graph_data.get("vertices") or []
    edges = graph_data.get("edges") or []

    if not isinstance(vertices, list):
        raise TypeError(f"'vertices' must be a list, got {type(vertices).__name__}")
    if not isinstance(edges, list):
        raise TypeError(f"'edges' must be a list, got {type(edges).__name__}")

    # Build a mapping from vertex ID -> display name for resolving edge endpoints.
    id_to_name = _build_id_to_name_map(vertices)

    # Auto-detect extract type if not provided.
    if extract_type is None:
        if edges and any("start" in edge and "end" in edge for edge in edges if isinstance(edge, dict)):
            extract_type = "triples"
        else:
            extract_type = "property_graph"

    candidate_vertices: List[Dict[str, Any]] = []
    for vertex in vertices:
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label", "")
        name = _vertex_name(vertex)
        properties = vertex.get("properties") or {}
        candidate_vertices.append(
            {
                "label": label,
                "name": name,
                "properties": properties if isinstance(properties, dict) else {},
            }
        )

    candidate_edges: List[Dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if extract_type == "triples":
            label = edge.get("type", "")
            raw_out = edge.get("start")
            raw_in = edge.get("end")
        else:
            label = edge.get("label", "")
            raw_out = edge.get("outV")
            raw_in = edge.get("inV")

        if raw_out is None or raw_in is None:
            # Skip malformed edges rather than crashing.
            continue

        properties = edge.get("properties") or {}
        candidate_edges.append(
            {
                "label": label,
                "outV": _resolve_endpoint(raw_out, id_to_name),
                "inV": _resolve_endpoint(raw_in, id_to_name),
                "properties": properties if isinstance(properties, dict) else {},
            }
        )

    return {"candidate_vertices": candidate_vertices, "candidate_edges": candidate_edges}


def normalize_schema(schema: Union[str, Dict[str, Any], None]) -> Dict[str, Any]:
    """Convert a JSON-string schema into the object expected by ExtractionRunner.

    The GraphExtractFlow pipeline may expose the graph schema as a JSON string.
    This helper parses it once so that benchmark inputs have ``data["schema"]``
    as a Python dict.

    Args:
        schema: A JSON string, an existing dict, or ``None``.

    Returns:
        Parsed schema dict (empty dict for ``None``).
    """
    if schema is None:
        return {}
    if isinstance(schema, str):
        return json.loads(schema)
    if isinstance(schema, dict):
        return schema
    raise TypeError(f"schema must be a dict, JSON string or None, got {type(schema).__name__}")


# Fields that are produced by the pipeline and should be forwarded unchanged
# to the benchmark sample (gold annotations, trace info, etc.).
_PRESERVED_SAMPLE_FIELDS = {
    "sample_id",
    "input_text",
    "question",
    "gold_vertices",
    "gold_edges",
    "raw_responses",
    "parse_results",
}


def normalize_extraction_output(
    pipeline_output: Union[str, Dict[str, Any]],
    extract_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a HugeGraph-LLM extraction pipeline output to benchmark format.

    Handles:

    * ``schema`` JSON string -> dict (via :func:`normalize_schema`).
    * ``vertices`` / ``edges`` -> ``candidate_vertices`` / ``candidate_edges``
      (via :func:`normalize_graph_extract`).
    * Preserves gold annotations and trace fields such as ``raw_responses`` /
      ``parse_results`` when ``collect_trace=True`` was enabled locally.

    Args:
        pipeline_output: Pipeline output dict or JSON string.
        extract_type: Optional extraction mode hint (``"property_graph"`` or
            ``"triples"``). Passed through to :func:`normalize_graph_extract`.

    Returns:
        Benchmark-compatible extraction sample dict.

    Example:
        >>> output = {
        ...     "schema": '{"vertexlabels": [...], "edgelabels": [...]}',
        ...     "vertices": [{"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}}],
        ...     "edges": [{"label": "knows", "outV": "1:Alice", "inV": "1:Bob"}],
        ...     "input_text": "Alice knows Bob.",
        ... }
        >>> normalize_extraction_output(output)
        {
            "schema": {"vertexlabels": [...], "edgelabels": [...]},
            "candidate_vertices": [...],
            "candidate_edges": [...],
            "input_text": "Alice knows Bob.",
        }
    """
    if isinstance(pipeline_output, str):
        pipeline_output = json.loads(pipeline_output)
    if not isinstance(pipeline_output, dict):
        raise TypeError(
            f"pipeline_output must be a dict or JSON string, got {type(pipeline_output).__name__}"
        )

    normalized: Dict[str, Any] = {}
    if "schema" in pipeline_output:
        normalized["schema"] = normalize_schema(pipeline_output["schema"])

    normalized.update(normalize_graph_extract(pipeline_output, extract_type=extract_type))

    for key in _PRESERVED_SAMPLE_FIELDS:
        if key in pipeline_output:
            normalized[key] = pipeline_output[key]

    return normalized
