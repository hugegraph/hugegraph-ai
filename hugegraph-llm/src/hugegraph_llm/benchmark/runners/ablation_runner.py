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

"""Runner for ablation study evaluation (4-mode comparison)."""

import logging
from typing import Any, Dict, List

from hugegraph_llm.benchmark.models.result import BenchmarkResult, SampleResult
from hugegraph_llm.benchmark.runners.base_runner import BaseRunner

logger = logging.getLogger(__name__)

# Answer mode keys present in each sample
_ANSWER_MODES = ("raw", "vector_only", "graph_only", "graph_vector")


class AblationRunner(BaseRunner):
    """Run ablation experiment comparing four answer modes.

    Expected data format::

        {
            "samples": [
                {
                    "sample_id": "abl_001",
                    "question": "...",
                    "gold_answer": "...",
                    "raw_answer": "...",
                    "vector_only_answer": "...",
                    "graph_only_answer": "...",
                    "graph_vector_answer": "..."
                }
            ]
        }

    For each sample the runner evaluates all four answer variants against
    the gold answer using the requested metrics.  Overall scores are keyed
    as ``{mode}_{metric_name}`` (e.g. ``raw_token_f1``).
    """

    def run(
        self,
        data_path: str,
        answer_metrics: List[str],
        language: str = "en",
        llm: Any = None,
    ) -> BenchmarkResult:
        """Execute ablation benchmark.

        Args:
            data_path: Path to the JSON data file.
            answer_metrics: Metric names to evaluate per answer mode.
            language: Language code ('en' or 'zh').
            llm: Optional LLM instance for LLM-based metrics (offline mode: None).

        Returns:
            Aggregated BenchmarkResult with per-mode overall scores.
        """
        self._errors.clear()
        data = self._load_data(data_path)

        samples = data.get("samples", [])

        metric_instances = self._create_metric_instances(answer_metrics)

        result = self._create_result(
            mode="ablation",
            language=language,
            metrics=answer_metrics,
            data_path=data_path,
        )

        def process_sample(sample: Dict[str, Any]) -> SampleResult:
            sample_id = sample["sample_id"]
            sample_result = SampleResult(
                sample_id=sample_id,
                question_type=sample.get("question_type"),
            )
            gold_answer = sample.get("gold_answer", "")

            for mode in _ANSWER_MODES:
                answer_key = f"{mode}_answer"
                prediction = sample.get(answer_key, "")

                for metric_name, metric in metric_instances.items():
                    context_key = f"{mode}_context"
                    scores = self._run_metric_safe(
                        metric=metric,
                        prediction=prediction,
                        reference=gold_answer,
                        sample_id=f"{sample_id}/{mode}",
                        language=language,
                        question=sample.get("question", ""),
                        context=sample.get(context_key, []),
                        llm=llm,
                    )
                    # Prefix each score with the mode name
                    for k, v in scores.items():
                        sample_result.metrics[f"{mode}_{k}"] = v
            return sample_result

        for sample_result in self._run_samples_concurrent(samples, process_sample):
            result.samples.append(sample_result)

        self._finalize_result(result)
        return result
