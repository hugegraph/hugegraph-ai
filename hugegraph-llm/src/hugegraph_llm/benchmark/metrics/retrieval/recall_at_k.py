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

"""Recall@K metric for document retrieval evaluation.

Computes recall at multiple K values, following the HippoRAG 2
evaluation convention: for each k, recall = |retrieved_top_k ∩ gold| / |gold|.
"""

from typing import Any, Dict, List

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_doc_id


@MetricRegistry.register
class RecallAtK(BaseMetric):
    """Recall@K for document retrieval.

    Computes recall at each k in ``k_list``:
    ``recall@k = |top_k_retrieved ∩ gold| / |gold|``

    Registered name: ``recall_at_k``
    """

    name: str = "recall_at_k"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate recall at multiple K values.

        Args:
            prediction: List of retrieved doc IDs, ordered by rank.
            reference: List of gold doc IDs.
            **kwargs: Optional ``k_list`` (List[int], default [1, 5, 10, 20]).

        Returns:
            Dict with keys like ``recall@1``, ``recall@5``, etc.
        """
        k_list: List[int] = kwargs.get("k_list", [1, 5, 10, 20])

        pred_ids = prediction if isinstance(prediction, list) else []
        ref_ids = reference if isinstance(reference, list) else []

        gold_set = {normalize_doc_id(d) for d in ref_ids}

        result: Dict[str, float] = {}
        for k in k_list:
            top_k = {normalize_doc_id(d) for d in pred_ids[:k]}
            if len(gold_set) == 0:
                recall = 0.0
            else:
                recall = len(top_k & gold_set) / len(gold_set)
            result[f"recall@{k}"] = round(recall, 4)

        return result
