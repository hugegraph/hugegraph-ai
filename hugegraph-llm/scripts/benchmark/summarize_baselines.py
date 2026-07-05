#!/usr/bin/env python3
"""Summarize baseline JSONs for Issue #75 real-pipeline verification tables."""

import json
from pathlib import Path

BASE = Path("/Users/xg/Coding/PersonalFile/BaiduCoding/hugegraph-ai/hugegraph-llm/benchmark_data/outputs/baselines")

RETRIEVAL_DATASETS = [
    ("hotpotqa", 100),
    ("2wikimultihopqa", 100),
    ("musique", 50),
    ("graphrag_bench_novel", 1),
    ("graphrag_bench_medical", 203),
]

EXTRACTION_DATASETS = [
    ("text2kgbench_culture", 15),
    ("text2kgbench_movie", 84),
]


def load_overall(name: str):
    p = BASE / f"{name}_baseline.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("overall", {})


def fmt(value):
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return str(value)


def row_bmd(name, n):
    r = load_overall(name)
    a = load_overall(f"{name}_answer")
    return (
        f"| {name} | {n} | "
        f"{fmt(r.get('recall@5'))} | {fmt(r.get('hit_any@5'))} | {fmt(r.get('mrr'))} | "
        f"{fmt(a.get('answer_correctness'))} | {fmt(a.get('faithfulness'))} | {fmt(a.get('coverage'))} |"
    )


def row_grmd_retrieval(name, n):
    r = load_overall(name)
    a = load_overall(f"{name}_answer")
    return (
        f"| {name} | {n} | "
        f"{fmt(r.get('recall@5'))} | {fmt(r.get('hit_any@5'))} | {fmt(r.get('mrr'))} | "
        f"{fmt(r.get('context_relevancy'))} | {fmt(r.get('evidence_recall_llm'))} | "
        f"{fmt(a.get('answer_correctness'))} | {fmt(a.get('faithfulness'))} | {fmt(a.get('coverage'))} |"
    )


def row_report_retrieval(name):
    r = load_overall(name)
    a = load_overall(f"{name}_answer")
    return (
        f"| {name} | {fmt(r.get('recall@5'))} | {fmt(r.get('hit_any@5'))} | {fmt(r.get('mrr'))} | "
        f"{fmt(r.get('evidence_recall_llm'))} | {fmt(a.get('answer_correctness'))} | "
        f"{fmt(a.get('faithfulness'))} | {fmt(a.get('coverage'))} |"
    )


def schema_summary(o):
    keys = ["type_constraint_pass", "required_property_fill", "illegal_edge_rate"]
    vals = [o.get(k) for k in keys if o.get(k) is not None]
    if not vals:
        return "N/A"
    return " / ".join(f"{v:.2f}" for v in vals)


def structural_summary(o):
    vals = [o.get("orphan_edge_rate", 0), o.get("duplicate_edge_rate", 0), o.get("duplicate_entity_rate", 0)]
    return f"{1 - sum(vals):.2f}"


def graph_structure_summary(o):
    return f"{o.get('largest_component_ratio', 0):.2f}"


def row_grmd_extraction(name, n):
    o = load_overall(name)
    if o is None:
        return f"| {name} | {n} | — | — | — | — | — | — | — | — | — |"
    return (
        f"| {name} | {n} | {fmt(o.get('entity_f1'))} | {fmt(o.get('triple_f1'))} | {fmt(o.get('property_f1'))} | "
        f"{schema_summary(o)} | {structural_summary(o)} | "
        f"{fmt(o.get('json_parse_rate'))} | {graph_structure_summary(o)} | "
        f"{fmt(o.get('conflict_rate'))} | {fmt(o.get('temporal_valid_rate'))} |"
    )


def row_report_extraction(name):
    o = load_overall(name)
    if o is None:
        return f"| {name} | — | — | — | — | — | — | — |"
    return (
        f"| {name} | {fmt(o.get('entity_f1'))} | {fmt(o.get('triple_f1'))} | {fmt(o.get('property_f1'))} | "
        f"{fmt(o.get('json_parse_rate'))} | {schema_summary(o)} | "
        f"{fmt(o.get('conflict_rate'))} | {fmt(o.get('temporal_valid_rate'))} |"
    )


if __name__ == "__main__":
    print("=== BENCHMARK_DATASETS.md §8.5 ===")
    for name, n in RETRIEVAL_DATASETS:
        print(row_bmd(name, n))

    print("\n=== GRAPHRAG_BENCHMARK.md §17.5 Retrieval+Answer ===")
    for name, n in RETRIEVAL_DATASETS:
        print(row_grmd_retrieval(name, n))

    print("\n=== GRAPHRAG_BENCHMARK.md §17.5 Extraction ===")
    for name, n in EXTRACTION_DATASETS:
        print(row_grmd_extraction(name, n))

    print("\n=== experiment-report.md §9.4 Retrieval+Answer ===")
    for name, _ in RETRIEVAL_DATASETS:
        print(row_report_retrieval(name))

    print("\n=== experiment-report.md §9.4 Extraction ===")
    for name, _ in EXTRACTION_DATASETS:
        print(row_report_extraction(name))
