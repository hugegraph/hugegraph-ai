#!/usr/bin/env python3
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

"""Generate stratified/random subsets of benchmark datasets for Issue #75.

Usage:
    uv run python hugegraph-llm/scripts/benchmark/prepare_benchmark_subsets.py

Rules:
- Seed = 42 (fixed for reproducibility).
- GraphRAG-Bench Novel / Medical: 10% stratified by question_type.
- HotpotQA / 2WikiMultiHopQA: 10% random.
- MuSiQue: 5% random.
- Text2KGBench movie / culture: 10% random per domain.
- Reads existing full benchmark JSONs from
  `hugegraph-llm/benchmark_data/external/` and writes subsets to
  `hugegraph-llm/benchmark_data/external/subsets/`.
"""

from __future__ import annotations

import json
import logging
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
EXTERNAL_DIR = REPO_ROOT / "hugegraph-llm" / "benchmark_data" / "external"
SUBSET_OUTPUT_DIR = EXTERNAL_DIR / "subsets"

logger = logging.getLogger("prepare_benchmark_subsets")

# File name -> fraction
RETRIEVAL_SUBSETS = {
    "graphrag_bench_novel_retrieval.json": 0.10,
    "graphrag_bench_medical_retrieval.json": 0.10,
    "hotpotqa_retrieval.json": 0.10,
    "2wikimultihopqa_retrieval.json": 0.10,
    "musique_retrieval.json": 0.05,
}

EXTRACTION_SUBSETS = {
    "text2kgbench_movie_extraction.json": 0.10,
    "text2kgbench_culture_extraction.json": 0.10,
}


def _stratified_sample(samples: List[Dict[str, Any]], fraction: float, seed: int = 42) -> List[Dict[str, Any]]:
    """Stratified sample by question_type if present; otherwise random sample."""
    random.seed(seed)
    if not samples:
        return []

    has_type = any(s.get("question_type") for s in samples)
    if not has_type:
        k = max(1, int(len(samples) * fraction))
        return random.sample(samples, k)

    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        buckets[s.get("question_type", "Unknown")].append(s)

    selected: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        k = max(1, int(len(bucket) * fraction)) if len(bucket) * fraction >= 1 else 0
        if k > 0:
            selected.extend(random.sample(bucket, k))
    random.shuffle(selected)
    return selected


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def prepare_retrieval_subsets(seed: int = 42) -> None:
    """Generate stratified/random subsets for retrieval datasets."""
    for filename, fraction in RETRIEVAL_SUBSETS.items():
        full_path = EXTERNAL_DIR / filename
        if not full_path.exists():
            logger.warning("Full dataset not found: %s; skipping.", full_path)
            continue

        logger.info("Preparing subset for %s (fraction=%.0f%%)...", filename, fraction * 100)
        full_data = _load_json(full_path)
        samples = full_data.get("samples", [])
        selected = _stratified_sample(samples, fraction, seed)
        logger.info(
            "  %s: %d -> %d samples (%s)",
            filename,
            len(samples),
            len(selected),
            "stratified" if any(s.get("question_type") for s in samples) else "random",
        )
        _save_json({**full_data, "samples": selected}, SUBSET_OUTPUT_DIR / filename)


def prepare_extraction_subsets(seed: int = 42) -> None:
    """Generate random subsets for Text2KGBench domains."""
    random.seed(seed)
    for filename, fraction in EXTRACTION_SUBSETS.items():
        full_path = EXTERNAL_DIR / filename
        if not full_path.exists():
            logger.warning("Full dataset not found: %s; skipping.", full_path)
            continue

        logger.info("Preparing subset for %s (fraction=%.0f%%)...", filename, fraction * 100)
        full_data = _load_json(full_path)
        samples = full_data.get("samples", [])
        k = max(1, int(len(samples) * fraction))
        selected = random.sample(samples, k)
        logger.info("  %s: %d -> %d samples (random)", filename, len(samples), len(selected))
        _save_json({**full_data, "samples": selected}, SUBSET_OUTPUT_DIR / filename)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger.info("Generating benchmark subsets with seed=42...")
    logger.info("Reading full datasets from: %s", EXTERNAL_DIR)
    logger.info("Output directory: %s", SUBSET_OUTPUT_DIR)
    prepare_retrieval_subsets(seed=42)
    prepare_extraction_subsets(seed=42)
    logger.info("Done. Subsets written to %s", SUBSET_OUTPUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
