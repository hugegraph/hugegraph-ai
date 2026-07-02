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

"""Runner for document retrieval evaluation."""

import logging
from typing import Any, Dict, List, Optional

from hugegraph_llm.benchmark.models.result import BenchmarkResult, SampleResult
from hugegraph_llm.benchmark.runners.base_runner import BaseRunner

logger = logging.getLogger(__name__)


class RetrievalRunner(BaseRunner):
    """Run retrieval evaluation against gold-standard document sets.

    Expected data format::

        {
            "samples": [
                {
                    "sample_id": "ret_001",
                    "question": "...",
                    "gold_docs": ["doc1", "doc2"],
                    "retrieved_docs": ["doc1", "doc3", "doc4", ...]
                }
            ]
        }
    """

    def run(
        self,
        data_path: str,
        metrics: List[str],
        k_list: Optional[List[int]] = None,
        language: str = "en",
        llm: Any = None,
    ) -> BenchmarkResult:
        """Execute retrieval benchmark.

        Args:
            data_path: Path to the JSON data file.
            metrics: List of metric names to evaluate.
            k_list: K values for rank-based metrics (e.g. [1, 5, 10]).
            language: Language code ('en' or 'zh') for LLM-Judge prompts.
            llm: Optional LLM instance for LLM-based metrics (offline mode: None).

        Returns:
            Aggregated BenchmarkResult.
        """
        self._errors.clear()
        data = self._load_data(data_path)

        samples = data.get("samples", [])

        metric_instances = self._create_metric_instances(metrics)

        result = self._create_result(
            mode="retrieval",
            metrics=metrics,
            k_list=k_list,
            language=language,
            data_path=data_path,
        )

        def process_sample(sample: Dict[str, Any]) -> SampleResult:
            sample_id = sample["sample_id"]
            sample_result = SampleResult(
                sample_id=sample_id,
                question_type=sample.get("question_type"),
            )

            kwargs: Dict[str, Any] = {"language": language}
            if k_list is not None:
                kwargs["k_list"] = k_list

            for name, metric in metric_instances.items():
                scores = self._run_metric_safe(
                    metric=metric,
                    prediction=sample.get("retrieved_docs", []),
                    reference=sample.get("gold_docs", []),
                    sample_id=sample_id,
                    question=sample.get("question", ""),
                    context=sample.get("retrieved_docs", []),
                    ground_truth=sample.get("gold_answer", sample.get("gold_docs", [])),
                    llm=llm,
                    **kwargs,
                )
                sample_result.metrics.update(scores)
            return sample_result

        for sample_result in self._run_samples_concurrent(samples, process_sample):
            result.samples.append(sample_result)

        self._finalize_result(result)
        return result
