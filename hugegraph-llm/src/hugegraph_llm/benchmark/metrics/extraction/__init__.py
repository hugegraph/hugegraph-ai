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

"""Extraction metrics for graph construction evaluation."""

from typing import Any, Dict


def _is_edge(item: Dict[str, Any]) -> bool:
    """Heuristic: an item is an edge if it has endpoint fields."""
    return any(key in item for key in ("outV", "inV", "outVLabel", "inVLabel", "source", "target"))


def _edge_out(item: Dict[str, Any]) -> Any:
    """Return an edge's source endpoint across supported sample formats."""
    return item.get("outV") or item.get("outVLabel") or item.get("source") or ""


def _edge_in(item: Dict[str, Any]) -> Any:
    """Return an edge's target endpoint across supported sample formats."""
    return item.get("inV") or item.get("inVLabel") or item.get("target") or ""


from hugegraph_llm.benchmark.metrics.extraction.conflict_detection import ConflictDetection  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.entity_f1 import EntityF1  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.graph_structure import GraphStructure  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.property_f1 import PropertyF1  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.schema_validity import SchemaValidity  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.structural_integrity import StructuralIntegrity  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.syntax_validity import SyntaxValidity  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.temporal_validity import TemporalValidity  # noqa: E402
from hugegraph_llm.benchmark.metrics.extraction.triple_f1 import TripleF1  # noqa: E402

__all__ = [
    "EntityF1",
    "TripleF1",
    "PropertyF1",
    "SchemaValidity",
    "StructuralIntegrity",
    "SyntaxValidity",
    "GraphStructure",
    "ConflictDetection",
    "TemporalValidity",
]
