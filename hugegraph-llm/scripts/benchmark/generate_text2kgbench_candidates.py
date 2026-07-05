# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate Text2KGBench extraction candidates using the GRAPH_EXTRACT flow.

This script takes a Text2KGBench extraction subset JSON (with `schema` and
`samples` containing `input_text`) and populates `candidate_vertices` and
`candidate_edges` for each sample by running the property-graph extraction
flow against the provided schema.

Usage:
    python scripts/benchmark/generate_text2kgbench_candidates.py \
        --input <text2kgbench_extraction.json> \
        --output <candidates_output.json>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hugegraph_llm.flows import FlowName  # noqa: E402
from hugegraph_llm.flows.scheduler import SchedulerSingleton  # noqa: E402
from hugegraph_llm.utils.log import log  # noqa: E402

logger = logging.getLogger("generate_text2kgbench_candidates")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Text2KGBench extraction candidates via graph_extract."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a Text2KGBench extraction JSON with 'schema' and 'samples'.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path where the candidate-enriched JSON will be written.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def load_input(input_path: str) -> Dict[str, Any]:
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "samples" not in data or not isinstance(data["samples"], list):
        raise ValueError("Input JSON must contain a 'samples' list.")
    if "schema" not in data or not isinstance(data["schema"], dict):
        raise ValueError("Input JSON must contain a 'schema' object.")
    return data


def _extract_property_names(props: Any) -> List[str]:
    """Return property names from a properties field (strings or objects)."""
    if not isinstance(props, list):
        return []
    names: List[str] = []
    for prop in props:
        if isinstance(prop, str):
            names.append(prop)
        elif isinstance(prop, dict) and prop.get("name"):
            names.append(prop["name"])
    return names


def normalize_schema(schema: Dict[str, Any]) -> str:
    """Repair a Text2KGBench schema so it satisfies CheckSchema.

    Text2KGBench schemas use the legacy shape but may omit ``propertykeys``,
    ``id_strategy``, ``nullable_keys`` and ``id`` fields that CheckSchema and
    Commit2Graph require.  This function fills them in deterministically.
    """
    schema = json.loads(json.dumps(schema))  # deep copy
    raw_vertices = schema.get("vertexlabels") or []
    raw_edges = schema.get("edgelabels") or []
    if not isinstance(raw_vertices, list):
        raw_vertices = []
    if not isinstance(raw_edges, list):
        raw_edges = []

    propertykeys: List[Dict[str, Any]] = []
    property_set: set = set()

    def _ensure_property(prop_name: str, data_type: str = "TEXT", cardinality: str = "SINGLE") -> None:
        if prop_name not in property_set:
            propertykeys.append({"name": prop_name, "data_type": data_type, "cardinality": cardinality})
            property_set.add(prop_name)

    vertexlabels: List[Dict[str, Any]] = []
    for idx, vertex in enumerate(raw_vertices, start=1):
        if not isinstance(vertex, dict):
            continue
        name = vertex.get("name")
        if not name:
            continue
        prop_names = _extract_property_names(vertex.get("properties"))
        primary_keys = vertex.get("primary_keys") or []
        if not isinstance(primary_keys, list):
            primary_keys = []
        # Ensure the primary key property exists.
        for pk in primary_keys:
            if pk not in prop_names:
                prop_names.append(pk)
        if not prop_names:
            prop_names = ["name"]
            primary_keys = ["name"]
        for prop_name in prop_names:
            _ensure_property(prop_name)
        primary_keys = [p for p in primary_keys if p in prop_names]
        if not primary_keys:
            primary_keys = [prop_names[0]]
        nullable_keys = [p for p in prop_names if p not in primary_keys]
        vertexlabels.append(
            {
                "id": vertex.get("id", idx),
                "name": name,
                "id_strategy": vertex.get("id_strategy", "PRIMARY_KEY"),
                "properties": prop_names,
                "primary_keys": primary_keys,
                "nullable_keys": nullable_keys,
            }
        )

    edgelabels: List[Dict[str, Any]] = []
    for idx, edge in enumerate(raw_edges, start=1):
        if not isinstance(edge, dict):
            continue
        name = edge.get("name")
        source_label = edge.get("source_label")
        target_label = edge.get("target_label")
        if not name or not source_label or not target_label:
            continue
        prop_names = _extract_property_names(edge.get("properties"))
        for prop_name in prop_names:
            _ensure_property(prop_name)
        edgelabels.append(
            {
                "id": edge.get("id", idx),
                "name": name,
                "source_label": source_label,
                "target_label": target_label,
                "properties": prop_names,
            }
        )

    return json.dumps(
        {"propertykeys": propertykeys, "vertexlabels": vertexlabels, "edgelabels": edgelabels},
        ensure_ascii=False,
        indent=2,
    )


def run_scheduler_flow(flow_name: str, *args, **kwargs) -> Any:
    """Convenience wrapper around SchedulerSingleton.schedule_flow."""
    scheduler = SchedulerSingleton.get_instance()
    return scheduler.schedule_flow(flow_name, *args, **kwargs)


def _parse_raw_response(raw_response: str) -> Dict[str, List[Dict[str, Any]]]:
    """Parse a raw LLM response into vertices and edges.

    LLM outputs vary: vertices may use ``properties.name`` or a flat ``name``
    field, and edges may use ``source/target`` or ``outV/inV``.  This function
    normalizes the common variants into a single structure.
    """
    import re

    text = re.sub(r"```\w*\n?", "", raw_response)
    text = re.sub(r"```", "", text).strip()
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        return {"vertices": [], "edges": []}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"vertices": [], "edges": []}

    if isinstance(data, list):
        # Some models return a flat list of items with a type field.
        vertices = [i for i in data if isinstance(i, dict) and i.get("type") == "vertex"]
        edges = [i for i in data if isinstance(i, dict) and i.get("type") == "edge"]
    elif isinstance(data, dict):
        vertices = data.get("vertices", []) if isinstance(data.get("vertices"), list) else []
        edges = data.get("edges", []) if isinstance(data.get("edges"), list) else []
    else:
        return {"vertices": [], "edges": []}

    normalized_vertices: List[Dict[str, Any]] = []
    for vertex in vertices:
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label")
        if not label:
            continue
        properties = vertex.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        name = properties.get("name")
        if name is None and "name" in vertex:
            name = vertex["name"]
            properties = {**properties, "name": name}
        if name is None:
            continue
        normalized_vertices.append({"label": label, "name": name, "properties": properties})

    normalized_edges: List[Dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        label = edge.get("label")
        out_v = edge.get("outV") or edge.get("source")
        in_v = edge.get("inV") or edge.get("target")
        if not label or not out_v or not in_v:
            continue
        normalized_edges.append(
            {
                "label": label,
                "outV": out_v,
                "inV": in_v,
                "properties": edge.get("properties", {}) if isinstance(edge.get("properties"), dict) else {},
            }
        )

    return {"vertices": normalized_vertices, "edges": normalized_edges}


def extract_candidates(schema_str: str, input_text: str) -> Dict[str, Any]:
    """Run GRAPH_EXTRACT on a single input text and return normalized candidates."""
    graph_data_json = run_scheduler_flow(
        FlowName.GRAPH_EXTRACT,
        schema_str,
        [input_text],
        "",
        "property_graph",
        collect_trace=True,
    )
    graph_data: Dict[str, Any] = {}
    if graph_data_json:
        graph_data = json.loads(graph_data_json) if isinstance(graph_data_json, str) else graph_data_json

    schema = json.loads(schema_str)
    vertex_primary_keys = {v["name"]: v.get("primary_keys", ["name"])[0] for v in schema.get("vertexlabels", [])}

    candidate_vertices: List[Dict[str, Any]] = []
    candidate_edges: List[Dict[str, Any]] = []

    # Prefer already-normalized vertices/edges from the flow when available.
    for vertex in graph_data.get("vertices", []):
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label")
        properties = vertex.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        pk = vertex_primary_keys.get(label, "name")
        name = properties.get(pk)
        if name is None:
            name = properties.get("name")
        if name is None:
            continue
        candidate_vertices.append({"label": label, "name": name, "properties": properties})

    for edge in graph_data.get("edges", []):
        if not isinstance(edge, dict):
            continue
        label = edge.get("label")
        out_v = edge.get("outV")
        in_v = edge.get("inV")
        if not label or not out_v or not in_v:
            continue
        candidate_edges.append(
            {"label": label, "outV": out_v, "inV": in_v, "properties": edge.get("properties", {})}
        )

    # If the flow failed to parse the LLM output, fall back to our own parser.
    if not candidate_vertices and not candidate_edges:
        for raw_response in graph_data.get("raw_responses", []):
            parsed = _parse_raw_response(raw_response)
            candidate_vertices.extend(parsed["vertices"])
            candidate_edges.extend(parsed["edges"])

    return {
        "candidate_vertices": candidate_vertices,
        "candidate_edges": candidate_edges,
        "raw_responses": graph_data.get("raw_responses", []),
        "parse_results": graph_data.get("parse_results", []),
    }


def process_sample(sample: Dict[str, Any], schema_str: str) -> Dict[str, Any]:
    """Populate candidate fields for one sample."""
    sample_id = sample.get("sample_id", "unknown")
    input_text = sample.get("input_text", "")
    if not input_text:
        logger.warning("Sample %s has no input_text; leaving candidates empty.", sample_id)
        sample["candidate_vertices"] = []
        sample["candidate_edges"] = []
        return sample

    logger.info("Extracting candidates for %s...", sample_id)
    try:
        candidates = extract_candidates(schema_str, input_text)
        sample["candidate_vertices"] = candidates["candidate_vertices"]
        sample["candidate_edges"] = candidates["candidate_edges"]
        sample["raw_responses"] = candidates["raw_responses"]
        sample["parse_results"] = candidates["parse_results"]
        logger.info(
            "Sample %s: %d vertices, %d edges.",
            sample_id,
            len(candidates["candidate_vertices"]),
            len(candidates["candidate_edges"]),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Sample %s failed: %s", sample_id, exc)
        logger.debug(traceback.format_exc())
        sample["candidate_vertices"] = []
        sample["candidate_edges"] = []
        sample["raw_responses"] = []
        sample["parse_results"] = []
    return sample


def main() -> None:
    args = parse_args()
    setup_logging()

    logger.info("Loading input from %s", args.input)
    data = load_input(args.input)
    samples = data["samples"]
    logger.info("Loaded %d samples.", len(samples))

    logger.info("Normalizing schema...")
    schema_str = normalize_schema(data["schema"])
    logger.info("Schema normalized (length %d).", len(schema_str))

    enriched_samples = [process_sample(sample, schema_str) for sample in samples]

    output_data = {**data, "samples": enriched_samples}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    logger.info("Wrote candidate output to %s", args.output)


if __name__ == "__main__":
    main()
