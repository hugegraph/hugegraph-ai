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

"""Abstract base class for benchmark runners.

Provides shared infrastructure for data loading, metric instantiation,
safe metric execution with error tracking, sample-level concurrency, and
result creation.  All concrete runners (Extraction, Retrieval, Ablation)
inherit from this.
"""

import json
import logging
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.models.result import BenchmarkResult, SampleResult

logger = logging.getLogger(__name__)

# Default sample-level concurrency.  LLM-Judge metrics are I/O-bound (waiting on
# the API), so threads yield near-linear speedup up to the provider's rate limit.
# DeepSeek/OpenAI comfortably tolerate >=20 concurrent requests; tune via --max-workers.
DEFAULT_MAX_WORKERS = 20


class BaseRunner(ABC):
    """Base class for all benchmark runners.

    Provides:
    - ``_load_data``: JSON file loader (override for other formats).
    - ``_create_metric_instances``: Instantiate metrics by name.
    - ``_run_metric_safe``: Execute a metric with error tracking (thread-safe).
    - ``_run_samples_concurrent``: Sample-level ThreadPool parallelism.
    - ``_create_result`` / ``_finalize_result``: BenchmarkResult factories.
    """

    def __init__(self, max_workers: int = DEFAULT_MAX_WORKERS) -> None:
        self._errors: List[Dict[str, str]] = []
        self._max_workers = max(1, int(max_workers))
        # Guards ``self._errors`` across worker threads.
        self._errors_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Data loading (Issue 6: DataLoader abstraction point)
    # ------------------------------------------------------------------

    def _load_data(self, data_path: str) -> dict:
        """Load data from a JSON file. Override for other formats."""
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Metric helpers
    # ------------------------------------------------------------------

    def _create_metric_instances(self, metrics: List[str]) -> Dict[str, BaseMetric]:
        """Instantiate metrics by name via the registry."""
        return {name: MetricRegistry.create(name) for name in metrics}

    def _run_metric_safe(
        self,
        metric: BaseMetric,
        prediction: Any,
        reference: Any,
        sample_id: str,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Run a metric with error tracking (thread-safe).

        On success returns the metric scores dict.
        On failure records the error in ``self._errors`` and returns ``{}``.
        """
        try:
            return metric.calculate(prediction=prediction, reference=reference, **kwargs)
        except Exception as e:
            with self._errors_lock:
                self._errors.append(
                    {
                        "sample_id": sample_id,
                        "metric": metric.name,
                        "error": str(e),
                    }
                )
            logger.exception("Metric %s failed for sample %s", metric.name, sample_id)
            return {}

    # ------------------------------------------------------------------
    # Sample-level concurrency
    # ------------------------------------------------------------------

    def _run_samples_concurrent(
        self,
        samples: List[Dict[str, Any]],
        process_fn: Callable[[Dict[str, Any]], SampleResult],
    ) -> List[SampleResult]:
        """Evaluate samples with thread-level concurrency.

        Each sample is processed by ``process_fn``; the metrics within a single
        sample still run sequentially (in its worker thread), while different
        samples run in parallel.  This is the sweet spot for LLM-Judge metrics:
        the LLM call is I/O-bound, so the GIL releases while waiting on the API
        and up to ``max_workers`` threads achieve near-linear speedup.

        Result order follows the input order (not completion order), so
        ``result.samples`` stays aligned with the source dataset for baseline
        comparison.

        Args:
            samples: List of sample dicts (as loaded from the data file).
            process_fn: Callable mapping one sample dict to a ``SampleResult``.
                Captured variables must be read-only across threads — metric
                instances are stateless and the shared OpenAI-backed LLM client
                is thread-safe, so the usual capture of ``metric_instances`` /
                ``llm`` / ``schema`` is safe.

        Returns:
            One ``SampleResult`` per sample, in input order.
        """
        total = len(samples)
        if total == 0:
            return []

        # Serial fast path: avoids thread-pool overhead for tiny runs or when
        # the user explicitly sets --max-workers 1 (e.g. debugging a metric).
        if self._max_workers <= 1 or total == 1:
            return [process_fn(s) for s in samples]

        results: List[Optional[SampleResult]] = [None] * total
        completed = 0
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_idx = {executor.submit(process_fn, sample): idx for idx, sample in enumerate(samples)}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    sample_id = samples[idx].get("sample_id", str(idx))
                    with self._errors_lock:
                        self._errors.append(
                            {
                                "sample_id": sample_id,
                                "metric": "__sample__",
                                "error": f"worker raised {type(e).__name__}: {e}",
                            }
                        )
                    logger.exception("Sample %s worker failed", sample_id)
                    results[idx] = SampleResult(sample_id=sample_id)
                completed += 1
                if completed % 50 == 0 or completed == total:
                    logger.info("Progress: %d/%d samples evaluated", completed, total)
        assert all(r is not None for r in results), "every slot must be filled"
        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Result factory
    # ------------------------------------------------------------------

    def _create_result(self, mode: str, **metadata: Any) -> BenchmarkResult:
        """Create a BenchmarkResult with standard metadata."""
        return BenchmarkResult(metadata={"mode": mode, **metadata})

    def _finalize_result(self, result: BenchmarkResult) -> None:
        """Compute overall scores, per-tier breakdown, and error tracking info."""
        result.compute_overall()
        result.compute_by_type()
        result.metadata["error_count"] = len(self._errors)
        result.metadata["max_workers"] = self._max_workers
        result.metadata["tiered"] = bool(result.by_type)
        if self._errors:
            result.metadata["errors"] = self._errors[:10]

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> BenchmarkResult:
        """Execute the benchmark. Subclasses must implement."""
