#!/usr/bin/env python3
"""Convert the 33-chunk car manual dataset into hugegraph_llm.benchmark extraction format.

For each chunk directory (e.g. baseline/<manual>/<manual>_ctxNNN_flat/):
  - chunk_text.md   -> input_text (body after '## 正文')
  - manual_result_full_recall.json -> gold vertices/edges
  - api_result.json                -> candidate vertices/edges

Outputs:
  - benchmark_data/outputs/car33/car33_api_vs_manual.json
  - benchmark_data/outputs/car33/car33_schema.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "benchmark_data" / "outputs" / "car33"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def extract_body(chunk_text: str) -> str:
    """Return the text body after the '## 正文' marker."""
    marker = "## 正文"
    idx = chunk_text.find(marker)
    if idx >= 0:
        return chunk_text[idx + len(marker) :].strip()
    return chunk_text.strip()


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def edge_to_vertex(edge: Dict[str, Any], endpoint: str) -> Dict[str, Any]:
    """Derive a vertex dict from an edge endpoint field."""
    if endpoint == "source":
        label = edge.get("source_type", "")
        name = edge.get("source_name", "")
    else:
        label = edge.get("target_type", "")
        name = edge.get("target_name", "")
    return {
        "label": label,
        "name": name,
        "properties": {"name": name, **edge.get("properties", {})},
    }


def unique_vertices(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive unique vertices from a list of edges."""
    seen: Set[Tuple[str, str]] = set()
    vertices: List[Dict[str, Any]] = []
    for edge in edges:
        for endpoint in ("source", "target"):
            label = edge.get(f"{endpoint}_type", "")
            name = edge.get(f"{endpoint}_name", "")
            if not label or not name:
                continue
            key = (label, name)
            if key in seen:
                continue
            seen.add(key)
            vertices.append(
                {
                    "label": label,
                    "name": name,
                    "properties": {"name": name, **edge.get("properties", {})},
                }
            )
    return vertices


def normalize_edges(edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert edges to benchmark format (outV/inV)."""
    out: List[Dict[str, Any]] = []
    for edge in edges:
        etype = edge.get("type") or edge.get("label")
        source = edge.get("source_name")
        target = edge.get("target_name")
        if not etype or not source or not target:
            continue
        out.append(
            {
                "label": etype,
                "outV": source,
                "inV": target,
                "properties": edge.get("properties", {}),
            }
        )
    return out


def build_schema(gold_edges: List[Dict[str, Any]], candidate_edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Infer a HugeGraph-compatible schema from observed edge types."""
    all_edges = gold_edges + candidate_edges
    vertex_labels: Set[str] = set()
    edge_types: Set[Tuple[str, str, str]] = set()
    for edge in all_edges:
        st = edge.get("source_type", "")
        tt = edge.get("target_type", "")
        et = edge.get("type") or edge.get("label", "")
        if st:
            vertex_labels.add(st)
        if tt:
            vertex_labels.add(tt)
        if st and tt and et:
            edge_types.add((st, et, tt))

    vertexlabels = []
    for idx, label in enumerate(sorted(vertex_labels), start=1):
        vertexlabels.append(
            {
                "id": idx,
                "name": label,
                "id_strategy": "PRIMARY_KEY",
                "properties": ["name"],
                "primary_keys": ["name"],
                "nullable_keys": [],
            }
        )

    edgelabels = []
    for idx, (source_label, name, target_label) in enumerate(sorted(edge_types), start=1):
        edgelabels.append(
            {
                "id": idx,
                "name": name,
                "source_label": source_label,
                "target_label": target_label,
                "properties": [],
            }
        )

    return {
        "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
        "vertexlabels": vertexlabels,
        "edgelabels": edgelabels,
    }


def collect_chunks(root: Path) -> List[Path]:
    """Return all *_flat directories under root."""
    return sorted([p for p in root.rglob("*_flat") if p.is_dir()])


def main() -> None:
    if len(sys.argv) < 2:
        root = Path("/tmp/car_dataset_33/baseline")
    else:
        root = Path(sys.argv[1])

    chunks = collect_chunks(root)
    print(f"Found {len(chunks)} chunk directories under {root}")

    samples: List[Dict[str, Any]] = []
    global_gold_edges: List[Dict[str, Any]] = []
    global_candidate_edges: List[Dict[str, Any]] = []

    for chunk_dir in chunks:
        chunk_id = chunk_dir.name.replace("_flat", "")
        chunk_text_path = chunk_dir / "chunk_text.md"
        manual_path = chunk_dir / "manual_result_full_recall.json"
        api_path = chunk_dir / "api_result.json"

        if not chunk_text_path.exists() or not manual_path.exists() or not api_path.exists():
            print(f"Skipping incomplete chunk: {chunk_dir}")
            continue

        chunk_text = chunk_text_path.read_text(encoding="utf-8")
        body = extract_body(chunk_text)

        manual_data = load_json(manual_path)
        api_data = load_json(api_path)

        gold_edges = normalize_edges(manual_data.get("edges", []))
        candidate_edges = normalize_edges(api_data.get("edges", []))

        global_gold_edges.extend(manual_data.get("edges", []))
        global_candidate_edges.extend(api_data.get("edges", []))

        sample = {
            "sample_id": chunk_id,
            "input_text": body,
            "gold_vertices": unique_vertices(manual_data.get("edges", [])),
            "gold_edges": gold_edges,
            "candidate_vertices": unique_vertices(api_data.get("edges", [])),
            "candidate_edges": candidate_edges,
            "raw_responses": [],
            "parse_results": [],
        }
        samples.append(sample)

    schema = build_schema(global_gold_edges, global_candidate_edges)

    output_data = {
        "schema": schema,
        "samples": samples,
    }

    out_path = OUT_DIR / "car33_api_vs_manual.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    schema_path = OUT_DIR / "car33_schema.json"
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(samples)} samples to {out_path}")
    print(f"Schema: {len(schema['vertexlabels'])} vertex labels, {len(schema['edgelabels'])} edge labels")


if __name__ == "__main__":
    main()
