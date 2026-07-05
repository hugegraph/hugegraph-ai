#!/usr/bin/env python3
"""Run HugeGraph-AI GRAPH_EXTRACT on the 33 car chunks using per-chunk schema.

The original all-chunk schema is too large for a single LLM prompt and caused
long retries. This script builds a small schema from each chunk's gold edges,
runs extraction concurrently, and writes a benchmark-compatible candidate JSON.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hugegraph_llm.config import prompt  # noqa: E402
from hugegraph_llm.flows.graph_extract import GraphExtractFlow  # noqa: E402
from hugegraph_llm.utils.log import log  # noqa: E402

logger = logging.getLogger("run_car33_pipeline_extraction")


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


def _extract_property_names(props: Any) -> List[str]:
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
    """Repair a schema so it satisfies CheckSchema."""
    schema = json.loads(json.dumps(schema))
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


def _parse_raw_response(raw_response: str) -> Dict[str, List[Dict[str, Any]]]:
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
        vertices = [i for i in data if isinstance(i, dict) and i.get("type") == "vertex"]
        edges = [i for i in data if isinstance(i, dict) and i.get("type") == "edge"]
    elif isinstance(data, dict):
        vertices = data.get("vertices", []) if isinstance(data.get("vertices"), list) else []
        edges = data.get("edges", []) if isinstance(data.get("edges"), list) else []
    else:
        return {"vertices": [], "edges": []}

    normalized_vertices: List[Dict[str, Any]] = []
    vid_to_name: Dict[str, str] = {}
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
        vid = vertex.get("id")
        if vid is not None:
            vid_to_name[str(vid)] = name

    normalized_edges: List[Dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        label = edge.get("label")
        out_v_raw = edge.get("outV") or edge.get("source")
        in_v_raw = edge.get("inV") or edge.get("target")
        if not label or not out_v_raw or not in_v_raw:
            continue
        out_v = vid_to_name.get(str(out_v_raw), re.sub(r"^\d+:", "", str(out_v_raw)))
        in_v = vid_to_name.get(str(in_v_raw), re.sub(r"^\d+:", "", str(in_v_raw)))
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
    """Run GRAPH_EXTRACT on a single input text using a fresh flow instance.

    SchedulerSingleton reuses pipelines and SchemaNode caches the first schema,
    so we build a fresh GraphExtractFlow per sample to ensure the per-chunk
    schema is actually used.
    """
    flow = GraphExtractFlow()
    pipeline = flow.build_flow(
        schema_str,
        [input_text],
        prompt.extract_graph_prompt,
        "property_graph",
        split_type="paragraph",
        collect_trace=True,
    )
    status = pipeline.init()
    if status.isErr():
        raise RuntimeError(f"Pipeline init failed: {status.getInfo()}")
    status = pipeline.run()
    if status.isErr():
        raise RuntimeError(f"Pipeline run failed: {status.getInfo()}")
    graph_data_json = flow.post_deal(pipeline)

    graph_data: Dict[str, Any] = {}
    if graph_data_json:
        graph_data = json.loads(graph_data_json) if isinstance(graph_data_json, str) else graph_data_json

    schema = json.loads(schema_str)
    vertex_primary_keys = {v["name"]: v.get("primary_keys", ["name"])[0] for v in schema.get("vertexlabels", [])}

    # Build id -> name mapping so edges can reference vertices by id or id:name.
    vid_to_name: Dict[str, str] = {}
    for vertex in graph_data.get("vertices", []):
        if not isinstance(vertex, dict):
            continue
        vid = vertex.get("id")
        properties = vertex.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        vname = properties.get("name")
        if vid is not None and vname is not None:
            vid_to_name[str(vid)] = vname

    def _resolve_edge_endpoint(endpoint: Any) -> str:
        """Resolve an edge endpoint to the referenced vertex name.

        GRAPH_EXTRACT returns endpoints as ``id:name`` (e.g. ``"1:自动远光灯开启指示灯"``).
        When the raw id is present in ``vid_to_name``, use the mapped name; otherwise
        strip the leading numeric id prefix and fall back to the remaining text.
        """
        if endpoint is None:
            return ""
        endpoint_str = str(endpoint)
        if endpoint_str in vid_to_name:
            return vid_to_name[endpoint_str]
        # Strip optional leading numeric id prefix like "1:"
        stripped = re.sub(r"^\d+:", "", endpoint_str)
        return stripped

    candidate_vertices: List[Dict[str, Any]] = []
    candidate_edges: List[Dict[str, Any]] = []

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
        out_v = _resolve_edge_endpoint(edge.get("outV"))
        in_v = _resolve_edge_endpoint(edge.get("inV"))
        if not label or not out_v or not in_v:
            continue
        candidate_edges.append(
            {"label": label, "outV": out_v, "inV": in_v, "properties": edge.get("properties", {}) if isinstance(edge.get("properties"), dict) else {}}
        )

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
    sample_id = sample.get("sample_id", "unknown")
    input_text = sample.get("input_text", "")
    if not input_text:
        logger.warning("Sample %s has no input_text; leaving candidates empty.", sample_id)
        sample["candidate_vertices"] = []
        sample["candidate_edges"] = []
        sample["raw_responses"] = []
        sample["parse_results"] = []
        return sample

    logger.info("Extracting pipeline candidates for %s (schema size %d)...", sample_id, len(schema_str))
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
    except Exception as exc:
        logger.error("Sample %s failed: %s", sample_id, exc)
        logger.debug(traceback.format_exc())
        sample["candidate_vertices"] = []
        sample["candidate_edges"] = []
        sample["raw_responses"] = []
        sample["parse_results"] = []
    return sample


def load_or_init_output(output_path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Load existing output to resume; otherwise return a fresh copy with candidates cleared."""
    if output_path.exists():
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if len(existing.get("samples", [])) == len(data["samples"]):
                # Only reuse if at least one sample has raw_responses (pipeline result).
                if any(s.get("raw_responses") for s in existing["samples"]):
                    return existing
        except Exception as exc:
            logger.warning("Failed to load existing output %s: %s", output_path, exc)

    fresh_samples = []
    for s in data["samples"]:
        fresh = dict(s)
        fresh.pop("candidate_vertices", None)
        fresh.pop("candidate_edges", None)
        fresh.pop("raw_responses", None)
        fresh.pop("parse_results", None)
        fresh_samples.append(fresh)
    return {**data, "samples": fresh_samples}


def save_output(output_path: Path, output_data: Dict[str, Any]) -> None:
    """Atomically write output JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(output_path)


def is_sample_done(sample: Dict[str, Any]) -> bool:
    """A sample is done only when pipeline has produced a raw_response."""
    return bool(sample.get("raw_responses"))


def main() -> None:
    setup_logging()
    input_path = REPO_ROOT / "benchmark_data" / "outputs" / "car33" / "car33_api_vs_manual.json"
    output_path = REPO_ROOT / "benchmark_data" / "outputs" / "car33" / "car33_pipeline_candidates.json"

    logger.info("Loading input from %s", input_path)
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples = data["samples"]
    logger.info("Loaded %d samples.", len(samples))

    output_data = load_or_init_output(output_path, data)
    existing_samples = output_data["samples"]

    schema_str = normalize_schema(data["schema"])
    logger.info("Using full schema (size %d).", len(schema_str))

    max_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    logger.info("Running extraction with max_workers=%d", max_workers)

    pending = [(i, s) for i, s in enumerate(samples) if not is_sample_done(existing_samples[i])]
    logger.info("Pending samples: %d", len(pending))

    def process_and_save(idx_sample: Tuple[int, Dict[str, Any]]) -> None:
        idx, sample = idx_sample
        result = process_sample(sample, schema_str)
        existing_samples[idx] = result
        save_output(output_path, output_data)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_and_save, item): item[0] for item in pending}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                future.result()
            except Exception as exc:
                logger.error("Future for sample %d failed: %s", idx, exc)

    save_output(output_path, output_data)
    logger.info("Wrote pipeline candidates to %s", output_path)


if __name__ == "__main__":
    main()
