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

"""CLI entry point for the HugeGraph-LLM benchmark module."""

import argparse
import json
import logging
import sys
from typing import Any, Dict, List, Optional

from openai import OpenAI

# Ensure all metrics are registered before any runner is used. Importing the
# package runs metrics/__init__.py, which imports every metric subpackage so
# each metric self-registers via MetricRegistry.
import hugegraph_llm.benchmark.metrics  # noqa: F401
from hugegraph_llm.benchmark.baseline.compare import BaselineComparator
from hugegraph_llm.benchmark.baseline.store import BaselineStore
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.models.result import BenchmarkResult
from hugegraph_llm.benchmark.reporters.markdown_reporter import MarkdownReporter
from hugegraph_llm.benchmark.runners.ablation_runner import AblationRunner
from hugegraph_llm.benchmark.runners.extraction_runner import ExtractionRunner
from hugegraph_llm.benchmark.runners.retrieval_runner import RetrievalRunner

logger = logging.getLogger(__name__)

# Default metric sets per mode (used when --metrics is omitted). Kept
# offline-friendly — LLM-Judge metrics are intentionally NOT in the defaults.
_DEFAULT_METRICS = {
    "extraction": ["entity_f1", "triple_f1", "schema_validity", "structural_integrity"],
    "retrieval": ["recall_at_k", "hit_at_k", "mrr"],
    "ablation": ["token_f1", "exact_match", "rouge_l"],
}

# Full allow-list per mode: the defaults above plus opt-in metrics valid for
# that mode. ``--metrics`` selections are kept iff they belong to the target
# mode's list, so ``--mode ablation --metrics coverage`` works while
# ``--mode retrieval --metrics entity_f1`` is rejected as a mode mismatch.
_MODE_ALLOWED_METRICS = {
    "extraction": _DEFAULT_METRICS["extraction"]
    + [
        "property_f1",
        "temporal_validity",
        "graph_structure",
        "syntax_validity",
        "conflict_detection",
    ],
    "retrieval": _DEFAULT_METRICS["retrieval"]
    + [
        "context_precision",
        "context_relevancy",
        "evidence_recall_llm",
    ],
    "ablation": _DEFAULT_METRICS["ablation"]
    + [
        "answer_correctness",
        "faithfulness",
        "coverage",
    ],
}


def _resolve_metrics(mode: str, user_metrics: Optional[str]) -> List[str]:
    """Return the list of metric names for a given mode."""
    if user_metrics:
        return [m.strip() for m in user_metrics.split(",") if m.strip()]
    if mode == "all":
        all_metrics: List[str] = []
        for v in _DEFAULT_METRICS.values():
            all_metrics.extend(v)
        return all_metrics
    return list(_DEFAULT_METRICS.get(mode, []))


def _unknown_metrics(metrics: List[str]) -> List[str]:
    available = set(MetricRegistry.list_metrics())
    return [metric for metric in metrics if metric not in available]


def _llm_metrics(metrics: List[str]) -> List[str]:
    selected = []
    for metric in metrics:
        metric_class = MetricRegistry.get(metric)
        if metric_class is not None and metric_class.requires_llm:
            selected.append(metric)
    return selected


def _configure_cli_logging() -> None:
    """Force benchmark logs to stderr so stdout stays JSON-clean.

    ``hugegraph_llm.utils.log`` (imported indirectly via config/init_llm)
    attaches Rich stdout handlers to both the root logger and the ``llm``
    logger at import time — intended for the server use case. The benchmark
    CLI prints machine-readable reports to stdout, so those handlers would
    corrupt the output. Call this after any import that triggers that module
    to strip stdout handlers and route all logs through stderr.
    """
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if getattr(h, "stream", None) is sys.stderr]
    if not root.handlers:
        _h = logging.StreamHandler(sys.stderr)
        _h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(_h)
        root.setLevel(logging.INFO)
    # The 'llm' logger gets its own stdout handler from utils.log; drop it
    # and let records propagate to the (stderr-only) root logger instead.
    _llm_logger = logging.getLogger("llm")
    _llm_logger.handlers = []
    _llm_logger.propagate = True


def _create_llm_client(settings: Optional[Any] = None) -> tuple[Optional[Any], Dict[str, Any]]:
    """Create an OpenAI-compatible LLM client for LLM-Judge metrics.

    Uses the project's LLMConfig only for endpoint / model / credentials.
    Generation parameters (temperature, seed) are fixed inside the benchmark
    module to ensure reproducible judge results.

    Args:
        settings: Optional LLM settings object (for testing). When omitted,
                  ``llm_settings`` is imported from ``hugegraph_llm.config``.

    Returns:
        (llm_client, metadata_dict). If creation fails, returns (None, {}).
    """
    # Force logs to stderr before importing config: config's module-level
    # ``LLMConfig()`` may emit errors via the ``llm`` logger, whose default
    # Rich handler writes to stdout and would corrupt the JSON report.
    import hugegraph_llm.utils.log  # noqa: F401  # side-effect: attaches handlers

    _configure_cli_logging()

    try:
        cfg = settings
        if cfg is None:
            from hugegraph_llm.config import llm_settings

            cfg = llm_settings
        model = getattr(cfg, "openai_chat_language_model", None) or "gpt-4.1-mini"
        client = OpenAI(
            api_key=getattr(cfg, "openai_chat_api_key", None) or "",
            base_url=getattr(cfg, "openai_chat_api_base", None),
        )
        temperature = 0.0
        seed = 42
        max_tokens = getattr(cfg, "openai_chat_tokens", None) or 2048

        class _JudgeLLM:
            """Thin wrapper exposing ``generate(prompt=...)`` over chat completions.

            Uses standard OpenAI messages format (``[{role, content}]``) and
            non-streaming chat completion calls.
            """

            def __init__(self, c, m, temp, s, mt):
                self._c = c
                self._m = m
                self._temperature = temp
                self._seed = s
                self._max_tokens = mt

            def generate(self, prompt="", messages=None, **kw):
                msgs = messages or [{"role": "user", "content": prompt}]
                response = self._c.chat.completions.create(
                    model=self._m,
                    messages=msgs,
                    temperature=self._temperature,
                    max_tokens=kw.get("max_tokens", self._max_tokens),
                    seed=self._seed,
                )
                return response.choices[0].message.content

        llm = _JudgeLLM(client, model, temperature, seed, max_tokens)
        logger.info(
            "LLM client: OpenAI-compatible, model=%s, temperature=%s, seed=%s",
            model,
            temperature,
            seed,
        )
        meta = {
            "model": model,
            "temperature": temperature,
            "seed": seed,
        }
        return llm, meta
    except Exception as e:
        logger.warning("LLM client creation failed: %s. LLM-Judge metrics will be skipped.", e)
        return None, {}


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


def _handle_run(args: argparse.Namespace) -> None:
    """Handle the ``run`` sub-command."""
    data_path: str = args.data
    if not _check_data_file(data_path):
        raise SystemExit(2)

    mode: str = args.mode
    metrics = _resolve_metrics(mode, args.metrics)
    unknown = _unknown_metrics(metrics)
    if unknown:
        print(f"Error: unknown metric(s): {', '.join(unknown)}", file=sys.stderr)
        raise SystemExit(2)
    llm_metric_names = _llm_metrics(metrics)
    if args.offline and llm_metric_names:
        print(
            "Error: LLM metric(s) require online mode and an LLM client: " + ", ".join(llm_metric_names),
            file=sys.stderr,
        )
        raise SystemExit(2)
    language: str = args.language
    data = _load_data_for_mode_detection(data_path)
    modes_to_run = _resolve_modes_to_run(mode, data)
    skipped_modes = _skipped_modes(mode, modes_to_run)
    if mode == "all" and skipped_modes:
        logger.info("Skipping unsupported modes for %s: %s", data_path, skipped_modes)
    if not modes_to_run:
        print(f"Error: data file does not match any benchmark mode: {data_path}", file=sys.stderr)
        raise SystemExit(2)

    # Create LLM client for LLM-Judge metrics (unless offline mode)
    llm = None
    llm_meta: Dict[str, Any] = {}
    if not args.offline:
        llm, llm_meta = _create_llm_client()
        if llm is None and llm_metric_names:
            print(
                "Error: LLM metric(s) require a configured LLM client: " + ", ".join(llm_metric_names),
                file=sys.stderr,
            )
            raise SystemExit(2)

    logger.info(
        "Mode=%s  Metrics=%s  Language=%s  LLM=%s  max_workers=%d",
        mode,
        metrics,
        language,
        "enabled" if llm else "offline",
        args.max_workers,
    )

    results: List[BenchmarkResult] = []
    max_workers = args.max_workers

    def metrics_for_mode(mode_key: str) -> List[str]:
        if mode == "all" and not args.metrics:
            return list(_DEFAULT_METRICS[mode_key])
        return _select_metrics(metrics, mode_key)

    if "extraction" in modes_to_run:
        runner = ExtractionRunner(max_workers=max_workers)
        r = runner.run(data_path=data_path, metrics=metrics_for_mode("extraction"), language=language, llm=llm)
        r.metadata["mode"] = "extraction"
        if skipped_modes:
            r.metadata["skipped_modes"] = skipped_modes
        results.append(r)

    if "retrieval" in modes_to_run:
        runner = RetrievalRunner(max_workers=max_workers)
        r = runner.run(data_path=data_path, metrics=metrics_for_mode("retrieval"), language=language, llm=llm)
        r.metadata["mode"] = "retrieval"
        if skipped_modes:
            r.metadata["skipped_modes"] = skipped_modes
        results.append(r)

    if "ablation" in modes_to_run:
        runner = AblationRunner(max_workers=max_workers)
        r = runner.run(data_path=data_path, answer_metrics=metrics_for_mode("ablation"), language=language, llm=llm)
        r.metadata["mode"] = "ablation"
        if skipped_modes:
            r.metadata["skipped_modes"] = skipped_modes
        results.append(r)

    # Attach LLM generation metadata to every result for reproducibility.
    if llm_meta:
        for r in results:
            r.metadata.update(llm_meta)

    # --smoke: keep only first 5 samples per result
    if args.smoke:
        for r in results:
            r.samples = r.samples[:5]
            r.compute_overall()
            r.compute_by_type()

    # --samples: filter by sample IDs
    if args.samples:
        sample_ids = {s.strip() for s in args.samples.split(",") if s.strip()}
        for r in results:
            r.samples = [s for s in r.samples if s.sample_id in sample_ids]
            r.compute_overall()
            r.compute_by_type()

    # Save baseline if requested
    if args.save_baseline:
        for r in results:
            path = args.save_baseline
            if len(results) > 1:
                # Append mode suffix when multiple results
                base, ext = path.rsplit(".", 1) if "." in path else (path, "json")
                path = f"{base}_{r.metadata.get('mode', 'unknown')}.{ext}"
            BaselineStore.save(r, path)
            print(f"Baseline saved to {path}", file=sys.stderr)

    # Output report
    fmt = args.format
    output = _render_results(results, fmt)

    if args.output:
        _write_report(output, args.output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)


def _handle_compare(args: argparse.Namespace) -> None:
    """Handle the ``compare`` sub-command."""
    baseline_path: str = args.baseline
    candidate_path: str = args.candidate

    if not _check_data_file(baseline_path):
        raise SystemExit(2)
    if not _check_data_file(candidate_path):
        raise SystemExit(2)

    baseline = BaselineStore.load(baseline_path)
    candidate = BaselineStore.load(candidate_path)

    reference = None
    if args.reference:
        if not _check_data_file(args.reference):
            raise SystemExit(2)
        reference = BaselineStore.load(args.reference)

    comparison = BaselineComparator.compare(baseline, candidate, reference=reference)

    fmt = args.format
    if fmt == "json":
        output = json.dumps(
            {
                "overall_diff": comparison.overall_diff,
                "overall_reference": comparison.overall_reference,
                "regressed_samples": comparison.regressed_samples,
                "improved_samples": comparison.improved_samples,
                "delta": comparison.delta,
            },
            indent=2,
            ensure_ascii=False,
        )
    else:
        output = MarkdownReporter.report(candidate, comparison=comparison)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Comparison report written to {args.output}", file=sys.stderr)
    else:
        print(output)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_data_file(path: str) -> bool:
    """Verify that a data file exists; print friendly error if not."""
    import os

    if not os.path.isfile(path):
        print(f"Error: data file not found: {path}", file=sys.stderr)
        return False
    return True


def _load_data_for_mode_detection(path: str) -> Dict[str, Any]:
    """Load the benchmark input once to detect which runner schemas it supports."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON data file {path}: {e}", file=sys.stderr)
        raise SystemExit(2) from e
    if not isinstance(data, dict):
        print(f"Error: benchmark data must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def _sample_has_any(sample: Dict[str, Any], keys: List[str]) -> bool:
    """Return True if a sample has any of the required schema keys."""
    return any(key in sample for key in keys)


def _detect_supported_modes(data: Dict[str, Any]) -> List[str]:
    """Infer benchmark modes supported by a data file without inventing defaults."""
    samples = data.get("samples", [])
    if not isinstance(samples, list) or not samples:
        return []

    modes: List[str] = []
    if any(
        isinstance(sample, dict)
        and _sample_has_any(sample, ["gold_vertices", "gold_edges", "candidate_vertices", "candidate_edges"])
        for sample in samples
    ):
        modes.append("extraction")
    if any(
        isinstance(sample, dict)
        and _sample_has_any(sample, ["gold_doc_ids", "retrieved_doc_ids", "retrieved_contexts"])
        for sample in samples
    ):
        modes.append("retrieval")
    if any(
        isinstance(sample, dict)
        and _sample_has_any(
            sample,
            ["raw_answer", "vector_only_answer", "graph_only_answer", "graph_vector_answer"],
        )
        for sample in samples
    ):
        modes.append("ablation")
    return modes


def _resolve_modes_to_run(mode: str, data: Dict[str, Any]) -> List[str]:
    """Resolve concrete runner modes, skipping incompatible modes only for all."""
    if mode != "all":
        return [mode]
    return _detect_supported_modes(data)


def _skipped_modes(requested_mode: str, modes_to_run: List[str]) -> List[str]:
    """Return mode names skipped by all-mode schema detection."""
    if requested_mode != "all":
        return []
    return [m for m in ("extraction", "retrieval", "ablation") if m not in modes_to_run]


def _result_envelope(results: List[BenchmarkResult]) -> Dict[str, Any]:
    """Serialize one or more benchmark results without ambiguous top-level JSON."""
    if len(results) == 1:
        return results[0].to_dict()
    return {
        "results": {
            str(result.metadata.get("mode", f"result_{idx}")): result.to_dict() for idx, result in enumerate(results)
        }
    }


def _render_results(results: List[BenchmarkResult], fmt: str) -> str:
    """Render benchmark results as JSON or Markdown."""
    if fmt == "json":
        return json.dumps(_result_envelope(results), indent=2, ensure_ascii=False)
    if len(results) == 1:
        return MarkdownReporter.report(results[0])
    return "\n\n---\n\n".join(MarkdownReporter.report(r) for r in results)


def _write_report(output: str, path: str) -> None:
    """Write an already-rendered report to disk."""
    import os

    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(output)


def _select_metrics(metrics: List[str], mode_key: str) -> List[str]:
    """Validate and return metrics valid for *mode_key*.

    Defaults (used when --metrics is omitted) stay offline-friendly; the full
    allow-list in ``_MODE_ALLOWED_METRICS`` also covers opt-in LLM-Judge
    metrics so they can be selected explicitly, e.g. ``--metrics coverage``.
    """
    allowed = set(_MODE_ALLOWED_METRICS.get(mode_key, []))
    invalid = [m for m in metrics if m not in allowed]
    if invalid:
        print(
            f"Error: metric(s) not valid for {mode_key} mode: {', '.join(invalid)}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return list(metrics)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the benchmark CLI."""
    parser = argparse.ArgumentParser(
        prog="hugegraph-benchmark",
        description="HugeGraph-LLM Benchmark Evaluation Tool",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run a benchmark evaluation")
    run_parser.add_argument(
        "--mode",
        choices=["extraction", "retrieval", "ablation", "all"],
        default="extraction",
        help="Evaluation mode (default: extraction)",
    )
    run_parser.add_argument("--data", required=True, help="Path to the JSON data file")
    run_parser.add_argument(
        "--metrics",
        default=None,
        help="Comma-separated metric names (default: auto-select by mode)",
    )
    run_parser.add_argument(
        "--language",
        choices=["en", "zh"],
        default="en",
        help="Language for normalization (default: en)",
    )
    run_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Only evaluate the first 5 samples",
    )
    run_parser.add_argument(
        "--samples",
        default=None,
        help="Comma-separated sample IDs to evaluate",
    )
    run_parser.add_argument(
        "--save-baseline",
        default=None,
        help="File path to save the result as a baseline",
    )
    run_parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: stdout)",
    )
    run_parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Report format (default: markdown)",
    )
    run_parser.add_argument(
        "--offline",
        action="store_true",
        help="Offline mode (skip LLM-dependent metrics)",
    )
    run_parser.add_argument(
        "--max-workers",
        type=int,
        default=20,
        help="Sample-level concurrency for LLM-Judge metrics (default: 20; use 1 for serial/debug)",
    )

    # --- compare ---
    cmp_parser = subparsers.add_parser("compare", help="Compare baseline and candidate results")
    cmp_parser.add_argument("--baseline", required=True, help="Path to baseline JSON file")
    cmp_parser.add_argument("--candidate", required=True, help="Path to candidate JSON file")
    cmp_parser.add_argument("--reference", default=None, help="Optional reference JSON file")
    cmp_parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Report format (default: markdown)",
    )
    cmp_parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: stdout)",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """Entry point for the benchmark CLI."""
    # force=True so our stderr handler is not shadowed if the runtime import
    # of hugegraph_llm.utils.log (via config/init_llm) configures the root
    # logger after this point — keeps stdout clean for machine-readable output.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        _handle_run(args)
    elif args.command == "compare":
        _handle_compare(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
