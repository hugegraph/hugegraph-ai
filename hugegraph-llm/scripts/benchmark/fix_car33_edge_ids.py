#!/usr/bin/env python3
"""Fix edge endpoint IDs in car33 pipeline candidate JSONs.

HugeGraph-AI GRAPH_EXTRACT outputs edges with ``outV``/``inV`` values like
``"1:自动远光灯开启指示灯"``, while vertices use the clean ``name`` field
(``"自动远光灯开启指示灯"``). This mismatch causes the benchmark to treat
all edges as orphan edges.

This script reads an existing candidate JSON (which already contains the
raw LLM outputs) and rewrites the edge endpoints by stripping the ``<id>:``
prefix. The fixed JSON can then be fed back into ``hugegraph-benchmark run``
without re-running the expensive LLM extraction.
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


def _strip_id_prefix(value: str) -> str:
    """Remove a leading numeric ID prefix such as '1:' from an endpoint name."""
    return re.sub(r"^\d+:", "", str(value))


def fix_sample(sample: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the sample with cleaned edge endpoints."""
    sample = dict(sample)
    fixed_edges: List[Dict[str, Any]] = []
    for edge in sample.get("candidate_edges", []):
        if not isinstance(edge, dict):
            continue
        fixed_edge = dict(edge)
        fixed_edge["outV"] = _strip_id_prefix(edge.get("outV", ""))
        fixed_edge["inV"] = _strip_id_prefix(edge.get("inV", ""))
        fixed_edges.append(fixed_edge)
    sample["candidate_edges"] = fixed_edges
    return sample


def fix_candidates(input_path: Path, output_path: Path) -> Dict[str, Any]:
    """Load candidate JSON, clean edge endpoints, and write the fixed version."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["samples"] = [fix_sample(s) for s in data.get("samples", [])]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix car33 pipeline candidate edge endpoint IDs.")
    parser.add_argument("--input", required=True, type=Path, help="Path to existing candidate JSON.")
    parser.add_argument("--output", required=True, type=Path, help="Path to write fixed candidate JSON.")
    args = parser.parse_args()

    data = fix_candidates(args.input, args.output)

    total_edges = sum(len(s.get("candidate_edges", [])) for s in data.get("samples", []))
    print(f"Fixed {total_edges} edges in {args.output}")


if __name__ == "__main__":
    main()
