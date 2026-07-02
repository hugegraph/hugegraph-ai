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

"""Graph structure metrics using networkx analysis.

Computes topological properties of the extracted graph including
node/edge counts, density, clustering coefficient, and connectivity.
"""

from typing import Any, Dict, List

import networkx as nx

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.extraction import _edge_in, _edge_out
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry


def _build_nx_graph(prediction: Dict[str, Any]) -> nx.Graph:
    """Build an undirected networkx Graph from prediction dict.

    Args:
        prediction: Dict with ``vertices`` and ``edges`` lists.

    Returns:
        An nx.Graph instance.
    """
    g = nx.Graph()

    vertices: List[Dict[str, Any]] = prediction.get("vertices", [])
    edges: List[Dict[str, Any]] = prediction.get("edges", [])

    if not isinstance(vertices, list):
        vertices = []
    if not isinstance(edges, list):
        edges = []

    # Add nodes
    for v in vertices:
        name = v.get("name")
        if not name and isinstance(v.get("properties"), dict):
            name = v["properties"].get("name", "")
        if name:
            label = str(v.get("label", ""))
            node_id = f"{label}:{name}" if label else str(name)
            g.add_node(node_id, label=label, name=str(name))

    # Add edges
    for e in edges:
        out_v = str(_edge_out(e))
        in_v = str(_edge_in(e))
        edge_label = str(e.get("label", ""))
        if out_v and in_v:
            g.add_edge(out_v, in_v, label=edge_label)

    return g


@MetricRegistry.register
class GraphStructure(BaseMetric):
    """Graph topology metrics computed via networkx.

    Expects prediction as a dict with ``vertices`` and ``edges`` lists.

    Metrics:
    - num_nodes: Number of nodes in the graph
    - num_edges: Number of edges in the graph
    - density: Graph density (nx.density)
    - clustering_coefficient: Average clustering coefficient
    - num_components: Number of connected components
    - largest_component_ratio: Fraction of nodes in the largest component

    Registered name: ``graph_structure``
    """

    name: str = "graph_structure"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate graph structure metrics.

        Args:
            prediction: Dict with ``vertices`` and ``edges`` lists.
            reference: Unused.

        Returns:
            Dict with graph topology metrics.
        """
        empty_result = {
            "num_nodes": 0.0,
            "num_edges": 0.0,
            "density": 0.0,
            "clustering_coefficient": 0.0,
            "num_components": 0.0,
            "largest_component_ratio": 0.0,
        }

        if not isinstance(prediction, dict):
            return empty_result

        g = _build_nx_graph(prediction)

        num_nodes = g.number_of_nodes()
        num_edges = g.number_of_edges()

        if num_nodes == 0:
            return empty_result

        density = nx.density(g)
        clustering = nx.average_clustering(g)
        num_components = nx.number_connected_components(g)

        # Largest connected component ratio
        component_sizes = [len(c) for c in nx.connected_components(g)]
        largest_size = max(component_sizes) if component_sizes else 0
        largest_ratio = largest_size / num_nodes if num_nodes > 0 else 0.0

        return {
            "num_nodes": float(num_nodes),
            "num_edges": float(num_edges),
            "density": round(density, 4),
            "clustering_coefficient": round(clustering, 4),
            "num_components": float(num_components),
            "largest_component_ratio": round(largest_ratio, 4),
        }
