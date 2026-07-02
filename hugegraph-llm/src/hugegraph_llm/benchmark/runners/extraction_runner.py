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

"""Runner for graph extraction evaluation."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from hugegraph_llm.benchmark.models.result import BenchmarkResult, SampleResult
from hugegraph_llm.benchmark.runners.base_runner import BaseRunner

logger = logging.getLogger(__name__)

# Maps each metric name to the (prediction_key, reference_key) in the sample dict.
# None means the metric needs a composite dict built from multiple keys.
_METRIC_DATA_MAPPING: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "entity_f1": ("candidate_vertices", "gold_vertices"),
    "triple_f1": ("candidate_edges", "gold_edges"),
    # Metrics below need a composite dict with vertices + edges
    "property_f1": (None, None),
    "schema_validity": (None, None),
    "structural_integrity": (None, None),
    "syntax_validity": (None, None),
    "graph_structure": (None, None),
    "conflict_detection": (None, None),
    "temporal_validity": (None, None),
}


def _build_composite_prediction(sample: Dict[str, Any], metric_name: str) -> Any:
    """Build the prediction value for metrics that need composite data."""
    if metric_name == "syntax_validity":
        return {
            "raw_responses": sample.get("raw_responses", []),
            "parse_results": sample.get("parse_results", []),
        }
    if metric_name in {"property_f1", "schema_validity"}:
        return sample.get("candidate_vertices", []) + sample.get("candidate_edges", [])
    # structural_integrity, graph_structure, conflict_detection, temporal_validity
    return {
        "vertices": sample.get("candidate_vertices", []),
        "edges": sample.get("candidate_edges", []),
    }


def _build_composite_reference(sample: Dict[str, Any], metric_name: str) -> Any:
    """Build the reference value for metrics that need composite data."""
    if metric_name == "syntax_validity":
        return None
    if metric_name in {"property_f1", "schema_validity"}:
        return sample.get("gold_vertices", []) + sample.get("gold_edges", [])
    return {
        "vertices": sample.get("gold_vertices", []),
        "edges": sample.get("gold_edges", []),
    }


class ExtractionRunner(BaseRunner):
    """Run graph construction evaluation against gold-standard annotations.

    Expected data format::

        {
            "schema": {"vertexlabels": [...], "edgelabels": [...]},
            "samples": [
                {
                    "sample_id": "ext_001",
                    "input_text": "...",
                    "gold_vertices": [...],
                    "gold_edges": [...],
                    "candidate_vertices": [...],
                    "candidate_edges": [...]
                }
            ]
        }
    """

    def run(
        self,
        data_path: str,
        metrics: List[str],
        language: str = "en",
        llm: Any = None,
    ) -> BenchmarkResult:
        """Execute extraction benchmark.

        Args:
            data_path: Path to the JSON data file.
            metrics: List of metric names to evaluate.
            language: Language code ('en' or 'zh').
            llm: Optional LLM instance for LLM-based metrics (offline mode: None).

        Returns:
            Aggregated BenchmarkResult.
        """
        self._errors.clear()
        data = self._load_data(data_path)

        schema = data.get("schema", {})
        samples = data.get("samples", [])

        metric_instances = self._create_metric_instances(metrics)

        result = self._create_result(
            mode="extraction",
            language=language,
            metrics=metrics,
            data_path=data_path,
        )

        def process_sample(sample: Dict[str, Any]) -> SampleResult:
            sample_id = sample["sample_id"]
            sample_result = SampleResult(
                sample_id=sample_id,
                question_type=sample.get("question_type"),
            )

            for name, metric in metric_instances.items():
                pred_key, ref_key = _METRIC_DATA_MAPPING.get(name, (None, None))

                if pred_key is not None:
                    prediction = sample.get(pred_key, [])
                    reference = sample.get(ref_key, []) if ref_key else []
                else:
                    prediction = _build_composite_prediction(sample, name)
                    reference = _build_composite_reference(sample, name)

                scores = self._run_metric_safe(
                    metric=metric,
                    prediction=prediction,
                    reference=reference,
                    sample_id=sample_id,
                    schema=schema,
                    language=language,
                    candidate_edges=sample.get("candidate_edges", []),
                    gold_edges=sample.get("gold_edges", []),
                    llm=llm,
                )
                sample_result.metrics.update(scores)
            return sample_result

        for sample_result in self._run_samples_concurrent(samples, process_sample):
            result.samples.append(sample_result)

        self._finalize_result(result)
        return result
