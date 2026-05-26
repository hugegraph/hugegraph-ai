# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""graph_data → change_plan 映射层 — 将用户输入的 {vertices, edges} 转为内部变更计划。

graph_data_to_change_plan() 是核心转换函数：
- 每个 vertex → create_vertex 操作
- 每个 edge → create_edge 操作（含端点匹配）
- 数字 id 和字符串 id 归一化处理

该模块不依赖 manage_graph_data.py，避免循环导入。
"""

from typing import Any

GraphChangePlan = dict[str, list[dict[str, Any]]]


def _change_plan_from_operations(operations: list[dict[str, Any]]) -> GraphChangePlan:
    return {"operations": operations}


def graph_data_to_change_plan(graph_data: dict[str, Any]) -> GraphChangePlan:
    """将图数据 {vertices, edges} 转为 change_plan {operations: [...]}。

    vertices 全部映射为 create_vertex，edges 全部映射为 create_edge。
    边端点通过顶点 id/properties 匹配确定 source_match/target_match。
    """
    operations: list[dict[str, Any]] = []
    vertex_matches = _vertex_matches_by_id(graph_data)
    for vertex in graph_data.get("vertices") or []:
        if not isinstance(vertex, dict):
            continue
        operations.append(
            {
                "op": "create_vertex",
                "label": vertex.get("label"),
                "properties": vertex.get("properties") or {},
            }
        )
    for edge in graph_data.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source_label = edge.get("source_label") or edge.get("outVLabel")
        target_label = edge.get("target_label") or edge.get("inVLabel")
        operations.append(
            {
                "op": "create_edge",
                "label": edge.get("label"),
                "source_label": source_label,
                "target_label": target_label,
                "source_match": _edge_endpoint_match(
                    edge=edge,
                    endpoint="source",
                    endpoint_label=source_label,
                    vertex_matches=vertex_matches,
                ),
                "target_match": _edge_endpoint_match(
                    edge=edge,
                    endpoint="target",
                    endpoint_label=target_label,
                    vertex_matches=vertex_matches,
                ),
                "properties": edge.get("properties") or {},
            }
        )
    return _change_plan_from_operations(operations)


def _vertex_matches_by_id(
    graph_data: dict[str, Any],
) -> dict[tuple[str, Any], dict[str, Any]]:
    """建立顶点 (label, id) → properties 的匹配索引。

    同时支持数字 id 和字符串 id 的归一化匹配。
    """
    matches: dict[tuple[str, Any], dict[str, Any]] = {}
    for vertex in graph_data.get("vertices") or []:
        if not isinstance(vertex, dict):
            continue
        label = vertex.get("label")
        vertex_id = vertex.get("id")
        properties = vertex.get("properties")
        if (
            isinstance(label, str)
            and vertex_id not in (None, "")
            and isinstance(properties, dict)
            and properties
        ):
            matches[(label, str(vertex_id))] = dict(properties)
    return matches


def _edge_endpoint_match(
    *,
    edge: dict[str, Any],
    endpoint: str,
    endpoint_label: str | None,
    vertex_matches: dict[tuple[str, Any], dict[str, Any]],
) -> dict[str, Any]:
    """确定边端点的匹配条件。

    优先级：显式 source/target dict > 顶点匹配索引 > 裸 id 回退。
    """
    if endpoint == "source":
        explicit = edge.get("source")
        vertex_id = edge.get("outV")
    else:
        explicit = edge.get("target")
        vertex_id = edge.get("inV")

    if isinstance(explicit, dict):
        return explicit
    if isinstance(endpoint_label, str) and vertex_id not in (None, ""):
        match = vertex_matches.get((endpoint_label, str(vertex_id)))
        if match is not None:
            return match
    return {"id": explicit or vertex_id}
