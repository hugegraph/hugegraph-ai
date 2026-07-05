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

_RANKING_METRICS = {"recall_at_k", "hit_at_k", "mrr"}
_CONTEXT_METRICS = {"context_precision", "context_relevancy", "evidence_recall_llm"}


def _require_list(sample: Dict[str, Any], field: str, sample_id: str) -> List[Any]:
    if field not in sample:
        raise ValueError(f"Retrieval sample {sample_id!r} missing required field '{field}'")
    value = sample[field]
    if not isinstance(value, list):
        raise ValueError(f"Retrieval sample {sample_id!r} field '{field}' must be a list")
    return value


def _doc_ids(sample: Dict[str, Any], field: str, sample_id: str) -> List[str]:
    values = _require_list(sample, field, sample_id)
    for value in values:
        if isinstance(value, (dict, list)):
            raise ValueError(f"Retrieval sample {sample_id!r} field '{field}' must contain document ids, not objects")
    return [str(value) for value in values]


def _texts(sample: Dict[str, Any], field: str, sample_id: str) -> List[str]:
    values = _require_list(sample, field, sample_id)
    for idx, value in enumerate(values):
        if not isinstance(value, str):
            raise ValueError(f"Retrieval sample {sample_id!r} field '{field}' item {idx} must be a string")
    return values


def _validate_sample_contract(sample: Dict[str, Any], metrics: List[str]) -> None:
    sample_id = str(sample.get("sample_id", "unknown"))
    metric_set = set(metrics)
    if metric_set & _RANKING_METRICS:
        _doc_ids(sample, "retrieved_doc_ids", sample_id)
        _doc_ids(sample, "gold_doc_ids", sample_id)
    if metric_set & _CONTEXT_METRICS:
        _texts(sample, "retrieved_contexts", sample_id)
    if "context_precision" in metric_set and "gold_answer" not in sample:
        raise ValueError(f"Retrieval sample {sample_id!r} missing required field 'gold_answer'")
    if "evidence_recall_llm" in metric_set:
        _texts(sample, "gold_evidence", sample_id)


class RetrievalRunner(BaseRunner):
    """Run retrieval evaluation against gold-standard document sets.

    Expected data format::

        {
            "samples": [
                {
                    "sample_id": "ret_001",
                    "question": "...",
                    "gold_doc_ids": ["doc1", "doc2"],
                    "retrieved_doc_ids": ["doc1", "doc3", "doc4", ...],
                    "retrieved_contexts": ["context text", ...],
                    "gold_evidence": ["gold evidence text", ...],
                    "gold_answer": "..."
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
        if set(metrics) & _CONTEXT_METRICS and llm is None:
            raise ValueError("Retrieval context metrics require an LLM client")
        data = self._load_data(data_path)

        samples = data.get("samples", [])
        for sample in samples:
            if isinstance(sample, dict):
                _validate_sample_contract(sample, metrics)
            else:
                raise ValueError("Retrieval samples must be JSON objects")

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
            metric_set = set(metrics)
            retrieved_doc_ids = (
                _doc_ids(sample, "retrieved_doc_ids", sample_id) if metric_set & _RANKING_METRICS else []
            )
            gold_doc_ids = _doc_ids(sample, "gold_doc_ids", sample_id) if metric_set & _RANKING_METRICS else []
            retrieved_contexts = (
                _texts(sample, "retrieved_contexts", sample_id) if metric_set & _CONTEXT_METRICS else []
            )
            gold_evidence = _texts(sample, "gold_evidence", sample_id) if "evidence_recall_llm" in metrics else []
            gold_answer = sample.get("gold_answer", "") if metric_set & _CONTEXT_METRICS else ""

            for name, metric in metric_instances.items():
                if name in _RANKING_METRICS:
                    prediction = retrieved_doc_ids
                    reference = gold_doc_ids
                elif name == "evidence_recall_llm":
                    prediction = retrieved_contexts
                    reference = gold_evidence
                else:
                    prediction = retrieved_contexts
                    reference = gold_answer
                scores = self._run_metric_safe(
                    metric=metric,
                    prediction=prediction,
                    reference=reference,
                    sample_id=sample_id,
                    question=sample.get("question", ""),
                    context=retrieved_contexts,
                    ground_truth=gold_answer,
                    llm=llm,
                    **kwargs,
                )
                sample_result.metrics.update(scores)
            return sample_result

        for sample_result in self._run_samples_concurrent(samples, process_sample):
            result.samples.append(sample_result)

        self._finalize_result(result)
        return result
