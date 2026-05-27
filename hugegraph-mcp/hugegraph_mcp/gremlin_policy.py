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

"""GremlinPolicy — 统一的 Gremlin 安全策略层。

所有 MCP Gremlin 读执行路径通过 GremlinPolicy.check_read() 做安全检查。
返回结构化决策，包含 allowed、classification、reason、error_type、suggestion。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hugegraph_mcp.gremlin_safety import classify_gremlin_read_safety

GremlinClassification = Literal["safe", "unsafe", "uncertain"]


@dataclass(frozen=True)
class GremlinDecision:
    """Gremlin 安全检查的结构化决策。"""

    allowed: bool
    classification: GremlinClassification
    reason: str
    error_type: str | None
    suggestion: str | None


class GremlinPolicy:
    """统一的 Gremlin 安全策略。

    所有 MCP Gremlin 读执行路径必须通过 check_read() 检查。
    """

    def check_read(self, gremlin_query: str) -> GremlinDecision:
        """检查 Gremlin 查询是否允许作为只读查询执行。

        Returns:
            GremlinDecision: 包含 allowed、classification、reason 等字段。
        """
        classification = classify_gremlin_read_safety(gremlin_query)

        if classification == "safe":
            return GremlinDecision(
                allowed=True,
                classification="safe",
                reason="Query is a known read-only traversal.",
                error_type=None,
                suggestion=None,
            )

        if classification == "unsafe":
            return GremlinDecision(
                allowed=False,
                classification="unsafe",
                reason="Query contains write or mutate operations.",
                error_type="UNSAFE_GREMLIN",
                suggestion=(
                    "Use execute_gremlin_write for write operations "
                    "when write access is enabled."
                ),
            )

        # classification == "uncertain"
        return GremlinDecision(
            allowed=False,
            classification="uncertain",
            reason="Query contains unknown or ambiguous steps; cannot confirm read-only safety.",
            error_type="UNSAFE_GREMLIN",
            suggestion="Use a clearly read-only Gremlin traversal starting with g.V() or g.E().",
        )


# 模块级单例
_policy = GremlinPolicy()


def check_gremlin_read(gremlin_query: str) -> GremlinDecision:
    """便捷函数：使用默认策略检查 Gremlin 查询。"""
    return _policy.check_read(gremlin_query)
