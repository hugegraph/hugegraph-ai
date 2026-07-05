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

"""Run the full 21-metric benchmark suite against generated outputs.

This script evaluates:
  - Retrieval outputs with 6 retrieval metrics
  - The same retrieval outputs with 6 answer-quality metrics
  - Text2KGBench candidate outputs with 9 extraction metrics

It saves both baseline JSON files and Markdown reports under
``benchmark_data/outputs/baselines/``.

Usage:
    python scripts/benchmark/run_benchmarks.py \
        --retrieval-dir hugegraph-llm/benchmark_data/outputs/hugegraph_retrieval \
        --text2kgbench-dir hugegraph-llm/benchmark_data/outputs/text2kgbench_candidates \
        --output-dir hugegraph-llm/benchmark_data/outputs/baselines
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Importing config first ensures dotenv is loaded before we build the LLM client.
from hugegraph_llm.benchmark.baseline.store import BaselineStore  # noqa: E402
from hugegraph_llm.benchmark.cli import _create_llm_client  # noqa: E402
from hugegraph_llm.benchmark.reporters.markdown_reporter import MarkdownReporter  # noqa: E402
from hugegraph_llm.benchmark.runners.answer_runner import AnswerRunner  # noqa: E402
from hugegraph_llm.benchmark.runners.extraction_runner import ExtractionRunner  # noqa: E402
from hugegraph_llm.benchmark.runners.retrieval_runner import RetrievalRunner  # noqa: E402
from hugegraph_llm.utils.log import log  # noqa: E402

logger = logging.getLogger("run_benchmarks")

RETRIEVAL_METRICS = [
    "recall_at_k",
    "hit_at_k",
    "mrr",
    "context_precision",
    "context_relevancy",
    "evidence_recall_llm",
]

ANSWER_METRICS = [
    "token_f1",
    "exact_match",
    "rouge_l",
    "answer_correctness",
    "faithfulness",
    "coverage",
]

EXTRACTION_METRICS = [
    "entity_f1",
    "triple_f1",
    "property_f1",
    "schema_validity",
    "structural_integrity",
    "syntax_validity",
    "graph_structure",
    "conflict_detection",
    "temporal_validity",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full 21-metric benchmark suite.")
    parser.add_argument(
        "--retrieval-dir",
        default="hugegraph-llm/benchmark_data/outputs/hugegraph_retrieval",
        help="Directory containing *_retrieval_output.json files.",
    )
    parser.add_argument(
        "--text2kgbench-dir",
        default="hugegraph-llm/benchmark_data/outputs/text2kgbench_candidates",
        help="Directory containing text2kgbench_*_candidates.json files.",
    )
    parser.add_argument(
        "--output-dir",
        default="hugegraph-llm/benchmark_data/outputs/baselines",
        help="Directory where baseline JSONs and Markdown reports are written.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="Sample-level concurrency for LLM-Judge metrics (default: 10).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip LLM-Judge metrics (evidence_recall_llm, answer_correctness, faithfulness, coverage).",
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


def create_llm() -> Tuple[Optional[Any], Dict[str, Any]]:
    """Create a reproducible LLM client for LLM-Judge metrics.

    Uses the benchmark-internal OpenAI-compatible client so judge generation
    parameters (temperature, seed) are fixed regardless of project config.
    """
    llm, meta = _create_llm_client()
    if llm is not None:
        logger.info("LLM-Judge enabled with model %s", meta.get("model"))
    else:
        logger.warning("Failed to create LLM client; LLM-Judge metrics will be skipped.")
    return llm, meta


def attach_llm_meta(result: Any, llm_meta: Dict[str, Any]) -> None:
    """Attach LLM generation metadata to a result for reproducibility."""
    if llm_meta:
        result.metadata.update(llm_meta)


def save_baseline_and_report(result, output_dir: Path, name: str, llm_meta: Dict[str, Any]) -> Dict[str, Path]:
    """Save a BenchmarkResult as JSON baseline and Markdown report."""
    attach_llm_meta(result, llm_meta)

    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = output_dir / f"{name}_baseline.json"
    report_path = output_dir / f"{name}_report.md"

    BaselineStore.save(result, str(baseline_path))

    report = MarkdownReporter.report(result)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    logger.info("Saved baseline %s and report %s", baseline_path, report_path)
    return {"baseline": str(baseline_path), "report": str(report_path)}


def run_retrieval_benchmark(
    input_path: Path, output_dir: Path, max_workers: int, llm: Any, llm_meta: Dict[str, Any]
) -> Dict[str, Path]:
    """Run retrieval metrics on a single retrieval output file."""
    metrics = list(RETRIEVAL_METRICS)
    if llm is None:
        metrics = [m for m in metrics if m != "evidence_recall_llm"]

    runner = RetrievalRunner(max_workers=max_workers)
    result = runner.run(
        data_path=str(input_path),
        metrics=metrics,
        k_list=[1, 5, 10],
        language="en",
        llm=llm,
    )
    name = input_path.stem.replace("_retrieval_output", "")
    return save_baseline_and_report(result, output_dir, name, llm_meta)


def run_answer_benchmark(
    input_path: Path, output_dir: Path, max_workers: int, llm: Any, llm_meta: Dict[str, Any]
) -> Dict[str, Path]:
    """Run answer-quality metrics on a retrieval output file."""
    metrics = list(ANSWER_METRICS)
    if llm is None:
        metrics = [m for m in metrics if m not in {"answer_correctness", "faithfulness", "coverage"}]

    runner = AnswerRunner(answer_key="graph_vector_answer", max_workers=max_workers)
    result = runner.run(
        data_path=str(input_path),
        metrics=metrics,
        language="en",
        llm=llm,
    )
    name = input_path.stem.replace("_retrieval_output", "") + "_answer"
    return save_baseline_and_report(result, output_dir, name, llm_meta)


def run_extraction_benchmark(
    input_path: Path, output_dir: Path, max_workers: int, llm: Any, llm_meta: Dict[str, Any]
) -> Dict[str, Path]:
    """Run extraction metrics on a Text2KGBench candidate file."""
    metrics = list(EXTRACTION_METRICS)
    runner = ExtractionRunner(max_workers=max_workers)
    result = runner.run(
        data_path=str(input_path),
        metrics=metrics,
        language="en",
        llm=llm,
    )
    name = input_path.stem.replace("_candidates", "")
    return save_baseline_and_report(result, output_dir, name, llm_meta)


def main() -> None:
    args = parse_args()
    setup_logging()

    retrieval_dir = Path(args.retrieval_dir)
    text2kgbench_dir = Path(args.text2kgbench_dir)
    output_dir = Path(args.output_dir)

    llm = None
    llm_meta: Dict[str, Any] = {}
    if not args.offline:
        llm, llm_meta = create_llm()

    artifacts: List[Dict[str, Any]] = []

    if retrieval_dir.exists():
        for input_path in sorted(retrieval_dir.glob("*_retrieval_output.json")):
            logger.info("Running retrieval benchmark for %s", input_path.name)
            artifacts.append(
                {
                    "dataset": input_path.stem,
                    "task": "retrieval",
                    **run_retrieval_benchmark(input_path, output_dir, args.max_workers, llm, llm_meta),
                }
            )
            logger.info("Running answer benchmark for %s", input_path.name)
            artifacts.append(
                {
                    "dataset": input_path.stem,
                    "task": "answer",
                    **run_answer_benchmark(input_path, output_dir, args.max_workers, llm, llm_meta),
                }
            )
    else:
        logger.warning("Retrieval output directory not found: %s", retrieval_dir)

    if text2kgbench_dir.exists():
        for input_path in sorted(text2kgbench_dir.glob("text2kgbench_*_candidates.json")):
            logger.info("Running extraction benchmark for %s", input_path.name)
            artifacts.append(
                {
                    "dataset": input_path.stem,
                    "task": "extraction",
                    **run_extraction_benchmark(input_path, output_dir, args.max_workers, llm, llm_meta),
                }
            )
    else:
        logger.warning("Text2KGBench candidate directory not found: %s", text2kgbench_dir)

    manifest_path = output_dir / "benchmark_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(artifacts, f, ensure_ascii=False, indent=2)
    logger.info("Benchmark manifest written to %s", manifest_path)


if __name__ == "__main__":
    main()
