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

"""Mean Reciprocal Rank (MRR) for document retrieval evaluation.

MRR = 1/rank of the first relevant document in the ranked retrieval list.
If no relevant document is found, MRR = 0.0.
"""

from typing import Any, Dict

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_doc_id


@MetricRegistry.register
class MRR(BaseMetric):
    """Mean Reciprocal Rank for document retrieval.

    Computes ``1/rank`` where rank is the position (1-indexed) of the
    first relevant document in the prediction list.

    Registered name: ``mrr``
    """

    name: str = "mrr"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate MRR.

        Args:
            prediction: List of retrieved doc IDs, ordered by rank.
            reference: List of gold doc IDs.

        Returns:
            Dict with key ``mrr``.
        """
        pred_ids = prediction if isinstance(prediction, list) else []
        ref_ids = reference if isinstance(reference, list) else []

        gold_set = {normalize_doc_id(d) for d in ref_ids}

        if not gold_set or not pred_ids:
            return {"mrr": 0.0}

        for rank, doc_id in enumerate(pred_ids, start=1):
            if normalize_doc_id(doc_id) in gold_set:
                return {"mrr": round(1.0 / rank, 4)}

        return {"mrr": 0.0}
