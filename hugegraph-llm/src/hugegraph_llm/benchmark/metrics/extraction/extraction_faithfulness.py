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

"""Extraction faithfulness — LLM judges whether each extracted item has textual support.

Unlike the F1 metrics, this is a GT-free metric: it only needs the candidate
extraction results and the original input text. The LLM judge checks each
vertex and edge for support in the source document.

Reference: deepeval FaithfulnessMetric (claims-vs-truths NLI pattern),
ragas NLIStatementPrompt (per-statement entailment verdict).
"""

import logging
from typing import Any, Dict, List, Optional

from hugegraph_llm.benchmark.llm_judge.judge_utils import (
    parse_json_response as _parse_json_response,
)
from hugegraph_llm.benchmark.llm_judge.judge_utils import (
    retry_llm_call,
)
from hugegraph_llm.benchmark.llm_judge.prompts import get_prompt
from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry

logger = logging.getLogger(__name__)

# Max items to send in a single LLM call (trim for cost control)
_MAX_ITEMS = 120
# Truncate input text to avoid excessive token usage
_MAX_INPUT_CHARS = 4000


def _format_item(
    idx: int,
    item: Dict[str, Any],
    item_type: str,
) -> str:
    """Format a single vertex or edge as a prompt line."""
    if item_type == "vertex":
        label = item.get("label", "")
        name = item.get("name")
        if not name and isinstance(item.get("properties"), dict):
            name = item["properties"].get("name", "")
        return f'[{idx}] {{"type": "vertex", "label": "{label}", "name": "{name}"}}'

    # edge
    out_v = str(_edge_out(item) or "?")
    label = str(item.get("label", "") or "?")
    in_v = str(_edge_in(item) or "?")
    return (
        f'[{idx}] {{"type": "edge", "label": "{label}", '
        f'"source": "{out_v}", "target": "{in_v}"}}'
    )


def _compute_extraction_faithfulness(
    llm: Any,
    prediction: Any,
    input_text: str,
    language: str = "en",
) -> Dict[str, Optional[float]]:
    """Core: judge each candidate vertex/edge for faithfulness to input text."""
    if llm is None:
        return {
            "extraction_faithfulness": None,
            "extraction_faithful_items": None,
            "extraction_total_items": None,
        }

    # prediction may be a composite dict from the runner:
    # {"vertices": [...], "edges": [...]}
    if isinstance(prediction, dict):
        vertices = prediction.get("vertices", prediction.get("candidate_vertices", []))
        edges = prediction.get("edges", prediction.get("candidate_edges", []))
    elif isinstance(prediction, list):
        vertices = prediction
        edges = []
    else:
        return {
            "extraction_faithfulness": None,
            "extraction_faithful_items": None,
            "extraction_total_items": None,
        }

    items: List[str] = []
    idx = 0
    for v in vertices[: _MAX_ITEMS]:
        items.append(_format_item(idx, v, "vertex"))
        idx += 1
    for e in edges[: _MAX_ITEMS - idx]:
        items.append(_format_item(idx, e, "edge"))
        idx += 1

    if not items:
        return {
            "extraction_faithfulness": 0.0,
            "extraction_faithful_items": 0,
            "extraction_total_items": 0,
        }

    text = (input_text or "")[:_MAX_INPUT_CHARS]

    prompt = get_prompt("EXTRACTION_FAITHFULNESS_PROMPT", language).format(
        input_text=text,
        items="\n".join(items),
    )

    verdicts: List[Dict[str, Any]] = []
    try:
        response = retry_llm_call(llm, prompt)
        data = _parse_json_response(response)
        if data and isinstance(data.get("verdicts"), list):
            verdicts = data["verdicts"]
    except Exception as e:
        logger.warning("Extraction faithfulness judgment failed: %s", e)

    total = len(items)
    faithful = sum(
        1 for v in verdicts
        if isinstance(v, dict) and v.get("verdict") in (1, "1", True)
    )

    score = faithful / total if total > 0 else 0.0

    return {
        "extraction_faithfulness": round(score, 4),
        "extraction_faithful_items": faithful,
        "extraction_total_items": total,
    }


@MetricRegistry.register
class ExtractionFaithfulness(BaseMetric):
    """GT-free faithfulness check: does each extracted item have textual support?

    Uses an LLM judge to check whether each candidate vertex/edge is supported
    by the original input text. This metric does NOT require gold annotations —
    it only needs the candidate extraction and the source document.

    Requires ``llm`` in kwargs and ``input_text`` in kwargs.
    Returns ``None`` when no LLM is available.

    Registered name: ``extraction_faithfulness``
    """

    name: str = "extraction_faithfulness"
    requires_llm: bool = True

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, Optional[float]]:
        """Calculate extraction faithfulness.

        Args:
            prediction: Candidate vertices/edges. Accepts either a composite
                       dict `{"vertices": [...], "edges": [...]}` (from the
                       runner) or a flat list of vertices.
            reference: Unused (GT-free metric).
            **kwargs: Must contain ``llm`` and ``input_text``.
                     Optional ``language`` ("en" or "zh").

        Returns:
            Dict with extraction_faithfulness (0-1),
            extraction_faithful_items, extraction_total_items.
        """
        llm = kwargs.get("llm")
        if llm is None:
            return {
                "extraction_faithfulness": None,
                "extraction_faithful_items": None,
                "extraction_total_items": None,
            }

        input_text = kwargs.get("input_text", "")
        language = kwargs.get("language", "en")
        return _compute_extraction_faithfulness(llm, prediction, input_text, language)
