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

"""Utilities for adapting HugeGraph-LLM RAG pipeline state to benchmark inputs."""

import json
from typing import Any, Dict, List, Optional, Union

# Modes supported by the RAG flows. Each mode determines which retrieved
# contexts are exported and which answer field is considered primary.
_RETRIEVAL_MODES = {
    "raw": {
        "context_sources": [],
        "answer_key": "raw_answer",
    },
    "vector_only": {
        "context_sources": ["vector_result"],
        "answer_key": "vector_only_answer",
    },
    "graph_only": {
        "context_sources": ["graph_result"],
        "answer_key": "graph_only_answer",
    },
    "graph_vector": {
        "context_sources": ["vector_result", "graph_result"],
        "answer_key": "graph_vector_answer",
    },
}


def _as_text_list(value: Any) -> List[str]:
    """Normalize a pipeline result field to a list of text strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def build_retrieval_sample_from_state(
    state: Union[str, Dict[str, Any]],
    mode: str = "graph_vector",
    sample_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a HugeGraph-LLM RAG ``WkFlowState`` dict into a benchmark sample.

    This adapter extracts ``retrieved_contexts`` from the intermediate retrieval
    results stored in ``WkFlowState``:

    * ``vector_result`` – chunk texts returned by vector search.
    * ``graph_result`` – textified graph knowledge snippets.

    The four RAG modes map to the context sources used by the corresponding
    pipeline flows:

    * ``raw`` – no retrieval context (the LLM answers from the question alone).
    * ``vector_only`` – ``vector_result`` only.
    * ``graph_only`` – ``graph_result`` only.
    * ``graph_vector`` – ``vector_result`` + ``graph_result`` (default).

    Args:
        state: ``WkFlowState.to_json()`` output or a JSON string.
        mode: One of ``"raw"``, ``"vector_only"``, ``"graph_only"``,
            ``"graph_vector"``.
        sample_id: Optional sample identifier. If omitted, the function tries
            ``state["sample_id"]`` and falls back to ``None``.

    Returns:
        Benchmark-compatible retrieval/answer sample dict.

    Note:
        Gold annotations (``gold_doc_ids``, ``gold_answer``, ``gold_evidence``)
        are not produced by the pipeline and must be supplied by the caller
        before passing the sample to a runner.

    Example:
        >>> state = {
        ...     "query": "What does Alice do?",
        ...     "vector_result": ["Alice is an engineer."],
        ...     "graph_result": ["Alice--[works_at]-->TechCorp"],
        ...     "graph_vector_answer": "Alice works at TechCorp.",
        ... }
        >>> build_retrieval_sample_from_state(state, mode="graph_vector", sample_id="q1")
        {
            "sample_id": "q1",
            "question": "What does Alice do?",
            "retrieved_contexts": ["Alice is an engineer.", "Alice--[works_at]-->TechCorp"],
            "raw_answer": "",
            "vector_only_answer": "",
            "graph_only_answer": "",
            "graph_vector_answer": "Alice works at TechCorp.",
        }
    """
    if isinstance(state, str):
        state = json.loads(state)
    if not isinstance(state, dict):
        raise TypeError(f"state must be a dict or JSON string, got {type(state).__name__}")

    if mode not in _RETRIEVAL_MODES:
        raise ValueError(f"Unknown retrieval mode {mode!r}; expected one of {list(_RETRIEVAL_MODES)}")

    config = _RETRIEVAL_MODES[mode]

    contexts: List[str] = []
    for source in config["context_sources"]:
        contexts.extend(_as_text_list(state.get(source)))

    sample: Dict[str, Any] = {
        "sample_id": sample_id if sample_id is not None else state.get("sample_id"),
        "question": state.get("question") or state.get("query", ""),
        "retrieved_contexts": contexts,
    }

    for answer_key in ("raw_answer", "vector_only_answer", "graph_only_answer", "graph_vector_answer"):
        sample[answer_key] = state.get(answer_key, "")

    return sample
