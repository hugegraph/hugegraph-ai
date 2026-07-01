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

"""Exact match metric for answer evaluation.

Reuses HippoRAG 2 QAExactMatch logic: normalizes both prediction and
reference(s), then checks for exact string equality. When multiple gold
answers exist, returns 1.0 if any matches.
"""

from typing import Any, Dict

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import normalize_answer


@MetricRegistry.register
class ExactMatch(BaseMetric):
    """Exact match after normalization for answer evaluation.

    Registered name: ``exact_match``
    """

    name: str = "exact_match"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate exact match against one or more gold answers.

        Args:
            prediction: Predicted answer text.
            reference: Gold answer(s) - a single string or list of strings.
            **kwargs: Optional 'language' key ('en' or 'zh').

        Returns:
            Dict with exact_match (0.0 or 1.0).
        """
        language = kwargs.get("language", "en")
        pred_norm = normalize_answer(str(prediction or ""), language)

        # Normalize reference to list
        if isinstance(reference, str):
            references = [reference]
        elif isinstance(reference, list):
            references = reference
        else:
            references = [str(reference)]

        # Check if any gold answer matches
        for ref in references:
            ref_norm = normalize_answer(str(ref or ""), language)
            if pred_norm == ref_norm:
                return {"exact_match": 1.0}

        return {"exact_match": 0.0}
