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

"""Hit@K metrics for document retrieval evaluation.

Two variants:
- HitAny@K: 1.0 if at least one gold doc appears in top-K, else 0.0
- HitAll@K: 1.0 if all gold docs appear in top-K, else 0.0
"""

from typing import Any, Dict, List

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_doc_id


@MetricRegistry.register
class HitAtK(BaseMetric):
    """Hit@K metrics (any and all variants).

    For each k in ``k_list``:
    - hit_any@k = 1.0 if ``set(top_k) & set(gold)`` is non-empty, else 0.0
    - hit_all@k = 1.0 if ``set(gold) ⊆ set(top_k)``, else 0.0

    Registered name: ``hit_at_k``
    """

    name: str = "hit_at_k"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate hit-any and hit-all at multiple K values.

        Args:
            prediction: List of retrieved doc IDs, ordered by rank.
            reference: List of gold doc IDs.
            **kwargs: Optional ``k_list`` (List[int], default [1, 5, 10, 20]).

        Returns:
            Dict with keys like ``hit_any@1``, ``hit_all@1``, etc.
        """
        k_list: List[int] = kwargs.get("k_list", [1, 5, 10, 20])

        pred_ids = prediction if isinstance(prediction, list) else []
        ref_ids = reference if isinstance(reference, list) else []

        gold_set = {normalize_doc_id(d) for d in ref_ids}

        result: Dict[str, float] = {}
        for k in k_list:
            top_k = {normalize_doc_id(d) for d in pred_ids[:k]}

            # Hit Any: at least one relevant doc in top-k
            if gold_set and top_k & gold_set:
                hit_any = 1.0
            else:
                hit_any = 0.0

            # Hit All: all relevant docs in top-k
            if gold_set and gold_set <= top_k:
                hit_all = 1.0
            else:
                hit_all = 0.0

            result[f"hit_any@{k}"] = hit_any
            result[f"hit_all@{k}"] = hit_all

        return result
