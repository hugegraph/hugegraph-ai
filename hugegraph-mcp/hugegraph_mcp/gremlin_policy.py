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

本模块同时拥有 Gremlin 安全分类器的实现（原 gremlin_safety.py）。
gremlin_safety.py 保留为兼容 wrapper，重新导出公共 API。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

GremlinClassification = Literal["safe", "unsafe", "uncertain"]
GremlinSafety = GremlinClassification  # 兼容别名

# ========== 分类器常量 ==========

_METHOD_RE = re.compile(r"\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_READ_START_RE = re.compile(r"^\s*g\s*\.\s*(?:V|E)\s*\(", re.IGNORECASE)
_DYNAMIC_MARKERS = ("${", "#{", "->")
_ALLOWED_ARG_TOKENS = {"true", "false", "null"}
_WRITE_METHODS = {
    "addv",
    "adde",
    "drop",
    "dropv",
    "drope",
    "remove",
    "clear",
    "sideeffect",
    "io",
    "call",
    "program",
}
_READ_METHODS = {
    "v",
    "e",
    "count",
    "limit",
    "range",
    "has",
    "haslabel",
    "hasid",
    "values",
    "valuemap",
    "id",
    "label",
    "keys",
    "elementmap",
    "properties",
    "out",
    "in",
    "both",
    "oute",
    "ine",
    "bothe",
    "outv",
    "inv",
    "bothv",
    "otherv",
    "path",
    "order",
    "group",
    "groupcount",
    "by",
    "dedup",
    "sample",
    "where",
    "not",
    "and",
    "or",
    "as",
    "select",
    "unfold",
    "coalesce",
    "optional",
    "repeat",
    "times",
    "until",
    "emit",
    "simplepath",
    "cyclicpath",
    "skip",
    "tail",
    "tolist",
    "toset",
    "explain",
    "profile",
}
_ANONYMOUS_READ_METHODS = {"outv", "inv", "bothv", "otherv"}


# ========== 分类器实现 ==========


def classify_gremlin_read_safety(gremlin_query: str) -> GremlinSafety:
    """Classify a Gremlin query for use by the read-only execution tool.

    The classifier intentionally rejects ambiguous queries. It is a conservative
    safety gate, not a complete Gremlin parser.
    """

    if not isinstance(gremlin_query, str) or not gremlin_query.strip():
        return "uncertain"

    query_without_strings = _strip_string_literals(gremlin_query)
    methods = _extract_method_names(query_without_strings)
    lowered_methods = [method.lower() for method in methods]

    if _has_unsafe_write_steps(query_without_strings, lowered_methods):
        return "unsafe"

    if _has_dynamic_construction_markers(gremlin_query, query_without_strings):
        return "uncertain"

    if not _READ_START_RE.search(query_without_strings):
        return "uncertain"

    if any(method not in _READ_METHODS for method in lowered_methods):
        return "uncertain"

    return "safe"


def is_safe_gremlin_read(gremlin_query: str) -> bool:
    """Return True only when the query is confidently read-only."""
    return classify_gremlin_read_safety(gremlin_query) == "safe"


def _extract_method_names(query_without_strings: str) -> list[str]:
    return _METHOD_RE.findall(query_without_strings)


def _has_unsafe_write_steps(
    query_without_strings: str, lowered_methods: list[str]
) -> bool:
    if any(method in _WRITE_METHODS for method in lowered_methods):
        return True

    if "property" in lowered_methods:
        return True

    if "iterate" in lowered_methods:
        return True

    return bool(
        re.search(r"\.\s*[VE]\s*\([^)]*\)\s*\.\s*drop\s*\(", query_without_strings)
    )


def _has_dynamic_construction_markers(
    original_query: str, query_without_strings: str
) -> bool:
    if any(marker in original_query for marker in _DYNAMIC_MARKERS):
        return True

    if "+" in query_without_strings:
        return True

    if "{" in query_without_strings or "}" in query_without_strings:
        return True

    if ";" in query_without_strings:
        return True

    if re.search(
        r"(?:^|[;\s])(?:def|var|String|query)\s+\w+\s*=", query_without_strings
    ):
        return True

    return _has_bare_identifier_arguments(query_without_strings)


def _has_bare_identifier_arguments(query_without_strings: str) -> bool:
    cleaned = re.sub(
        r"\.\s*[A-Za-z_][A-Za-z0-9_]*",
        " ",
        query_without_strings,
    )
    for method in _ANONYMOUS_READ_METHODS:
        cleaned = re.sub(
            rf"\b{method}\s*\(",
            "(",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = re.sub(r"^\s*[gG]\b", " ", cleaned)
    for token_match in re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", cleaned):
        token = token_match.group(0).lower()
        if token not in _ALLOWED_ARG_TOKENS:
            return True

    return False


def _strip_string_literals(query: str) -> str:
    """Replace string literal contents with spaces while preserving structure."""

    result: list[str] = []
    quote: str | None = None
    escaped = False

    for char in query:
        if quote is None:
            if char in {"'", '"'}:
                quote = char
                result.append(char)
            else:
                result.append(char)
            continue

        if escaped:
            escaped = False
            result.append(" ")
        elif char == "\\":
            escaped = True
            result.append(" ")
        elif char == quote:
            quote = None
            result.append(char)
        else:
            result.append(" ")

    if quote is not None:
        return query

    return "".join(result)


# ========== 结构化决策 ==========


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
        """检查 Gremlin 查询是否允许作为只读查询执行。"""
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
