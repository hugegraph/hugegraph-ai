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

"""Token-level F1 score for answer evaluation.

Reuses HippoRAG 2 QAF1Score logic: tokenizes prediction and reference(s),
computes Counter intersection for precision/recall/F1. When multiple gold
answers exist, takes the max F1 across them.
"""

from collections import Counter
from typing import Any, Dict, List

import numpy as np

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import tokenize


def _compute_token_f1_single(
    pred_tokens: List[str],
    ref_tokens: List[str],
) -> Dict[str, float]:
    """Compute token-level precision, recall, F1 for a single pair."""
    if not pred_tokens and not ref_tokens:
        return {"token_precision": 1.0, "token_recall": 1.0, "token_f1": 1.0}
    if not pred_tokens or not ref_tokens:
        return {"token_precision": 0.0, "token_recall": 0.0, "token_f1": 0.0}

    pred_counter = Counter(pred_tokens)
    ref_counter = Counter(ref_tokens)

    # Intersection: min count for each common token
    common = sum((pred_counter & ref_counter).values())

    precision = common / len(pred_tokens)
    recall = common / len(ref_tokens)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "token_precision": round(precision, 4),
        "token_recall": round(recall, 4),
        "token_f1": round(f1, 4),
    }


@MetricRegistry.register
class TokenF1(BaseMetric):
    """Token-level F1 score for answer evaluation.

    Registered name: ``token_f1``
    """

    name: str = "token_f1"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate token F1 against one or more gold answers.

        Args:
            prediction: Predicted answer text.
            reference: Gold answer(s) - a single string or list of strings.
            **kwargs: Optional 'language' key ('en' or 'zh').

        Returns:
            Dict with token_f1, token_precision, token_recall.
        """
        language = kwargs.get("language", "en")
        pred_str = str(prediction or "")
        # No stemming: aligns with HippoRAG 2 QAF1Score, which tokenizes via
        # normalize_answer().split() without a stemmer (MRQA official standard).
        pred_tokens = tokenize(pred_str, language)

        # Normalize reference to list
        if isinstance(reference, str):
            references = [reference]
        elif isinstance(reference, list):
            references = reference
        else:
            references = [str(reference)]

        # Compute F1 against each gold answer, take max
        all_scores = []
        for ref in references:
            ref_tokens = tokenize(str(ref or ""), language)
            scores = _compute_token_f1_single(pred_tokens, ref_tokens)
            all_scores.append(scores)

        if not all_scores:
            return {"token_f1": 0.0, "token_precision": 0.0, "token_recall": 0.0}

        # Aggregate: max F1 across gold answers, with corresponding P/R
        f1_values = [s["token_f1"] for s in all_scores]
        best_idx = int(np.argmax(f1_values))
        return all_scores[best_idx]
