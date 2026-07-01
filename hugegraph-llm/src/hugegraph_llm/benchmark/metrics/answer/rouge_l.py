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

"""ROUGE-L metric for answer evaluation.

English uses the official ``rouge_score`` package (Google's reference
implementation, same as GraphRAG-Benchmark, with ``use_stemmer=True``).
Chinese uses jieba tokenization + a self-contained LCS, because
``rouge_score`` drops non-ASCII characters and cannot score Chinese text.
"""

from typing import Any, Dict, List

from rouge_score import rouge_scorer

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry
from hugegraph_llm.benchmark.utils.normalize import tokenize


def _lcs_length(x: List[str], y: List[str]) -> int:
    """Compute the length of the Longest Common Subsequence via DP.

    Uses O(min(m,n)) space optimization with two rows.
    """
    m, n = len(x), len(y)
    if m == 0 or n == 0:
        return 0

    # Use shorter dimension for columns to save space
    if m < n:
        x, y = y, x
        m, n = n, m

    prev = [0] * (n + 1)
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if x[i - 1] == y[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, prev

    return prev[n]


@MetricRegistry.register
class RougeL(BaseMetric):
    """ROUGE-L metric based on Longest Common Subsequence.

    Registered name: ``rouge_l``
    """

    name: str = "rouge_l"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate ROUGE-L precision, recall, and F1.

        English: delegates to the official ``rouge_score`` package
        (``use_stemmer=True``), matching GraphRAG-Benchmark exactly.
        Chinese: jieba tokenization + self-contained LCS, because
        ``rouge_score`` drops non-ASCII text.

        When multiple gold answers are given, the max F1 (with its
        corresponding precision/recall) is returned.

        Args:
            prediction: Predicted answer text.
            reference: Gold answer(s) - a single string or list of strings.
            **kwargs: Optional 'language' key ('en' or 'zh').

        Returns:
            Dict with rouge_l_precision, rouge_l_recall, rouge_l_f1.
        """
        language = kwargs.get("language", "en")
        pred_str = str(prediction or "").strip()

        # Normalize reference to list
        if isinstance(reference, str):
            references = [reference]
        elif isinstance(reference, list):
            references = reference
        else:
            references = [str(reference)]

        ref_strs: List[str] = [str(r or "") for r in references]
        any_ref = any(r.strip() for r in ref_strs)

        # Edge cases: both empty → 1.0; prediction empty but ref non-empty → 0.0
        if not pred_str and not any_ref:
            return {"rouge_l_precision": 1.0, "rouge_l_recall": 1.0, "rouge_l_f1": 1.0}
        if not pred_str:
            return {"rouge_l_precision": 0.0, "rouge_l_recall": 0.0, "rouge_l_f1": 0.0}

        if language == "zh":
            return self._score_chinese(pred_str, ref_strs)
        return self._score_english(pred_str, ref_strs)

    @staticmethod
    def _score_english(pred_str: str, ref_strs: List[str]) -> Dict[str, float]:
        """Score via the official rouge_score package (GraphRAG-Bench align)."""
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        best = None
        for ref in ref_strs:
            if not ref.strip():
                continue
            # RougeScorer.score(target, prediction): precision/recall are
            # measured against the prediction, matching GraphRAG-Bench's
            # scorer.score(ground_truth, answer) call order.
            result = scorer.score(ref, pred_str)["rougeL"]
            if best is None or result.fmeasure > best.fmeasure:
                best = result
        if best is None:
            return {"rouge_l_precision": 0.0, "rouge_l_recall": 0.0, "rouge_l_f1": 0.0}
        return {
            "rouge_l_precision": round(best.precision, 4),
            "rouge_l_recall": round(best.recall, 4),
            "rouge_l_f1": round(best.fmeasure, 4),
        }

    @staticmethod
    def _score_chinese(pred_str: str, ref_strs: List[str]) -> Dict[str, float]:
        """Score via jieba + LCS (rouge_score drops non-ASCII text)."""
        best = (0.0, 0.0, 0.0)  # (precision, recall, f1)
        for ref in ref_strs:
            if not ref.strip():
                continue
            pred_tokens = tokenize(pred_str, "zh")
            ref_tokens = tokenize(ref, "zh")
            if not pred_tokens or not ref_tokens:
                continue
            lcs_len = _lcs_length(pred_tokens, ref_tokens)
            precision = lcs_len / len(pred_tokens)
            recall = lcs_len / len(ref_tokens)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
            if f1 > best[2]:
                best = (precision, recall, f1)
        return {
            "rouge_l_precision": round(best[0], 4),
            "rouge_l_recall": round(best[1], 4),
            "rouge_l_f1": round(best[2], 4),
        }
