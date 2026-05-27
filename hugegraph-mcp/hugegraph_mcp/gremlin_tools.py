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

"""Gremlin 执行层 — 封装 HugeGraph Gremlin 读写客户端。

所有 Gremlin 查询统一通过 GremlinExecutor 执行，对连接失败/认证错误/
HTTP 错误/语法错误做结构化错误收集，不抛异常到上层。
"""

import time
from typing import Any

import requests
from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.gremlin_policy import check_gremlin_read
from hugegraph_mcp.guard import Capability, guard_write

_cfg = MCPConfig.from_env()


class GremlinExecutor:
    """封装 HugeGraph Gremlin 读写客户端，自动处理 graphspace 兼容性。

    HugeGraph 1.7.0+ 支持 graph space，配置为空时回退到默认客户端。
    """

    def __init__(self, cfg: MCPConfig) -> None:
        self._cfg = cfg

    def _build_client(self) -> PyHugeClient:
        # graphspace 为空时跳过，保持与旧版 HugeGraph 的兼容性
        if self._cfg.graphspace and self._cfg.graphspace.strip():
            return PyHugeClient(
                url=self._cfg.url,
                graph=self._cfg.graph,
                user=self._cfg.user,
                pwd=self._cfg.password,
                graphspace=self._cfg.graphspace.strip(),
            )
        else:
            return PyHugeClient(
                url=self._cfg.url,
                graph=self._cfg.graph,
                user=self._cfg.user,
                pwd=self._cfg.password,
            )

    def get_read_client(self):
        return self._build_client().gremlin()

    def get_write_client(self):
        return self._build_client().gremlin()


# 模块级单例，避免重复构建客户端
_executor = GremlinExecutor(_cfg)

_GREMLIN_ERROR_TYPE_MAP = {
    "connection_error": ErrorType.CONNECTION_FAILED,
    "authentication_error": ErrorType.AUTHENTICATION_FAILED,
    "authorization_error": ErrorType.AUTHORIZATION_FAILED,
    "query_syntax_error": ErrorType.UNSAFE_GREMLIN,
}


def _get_read_client():
    return _executor.get_read_client()


def _get_write_client():
    return _executor.get_write_client()


def _gremlin_error_envelope(result: dict[str, Any]) -> dict[str, Any]:
    error_type = _GREMLIN_ERROR_TYPE_MAP.get(
        result.get("error_type"),
        ErrorType.CONNECTION_FAILED,
    )
    suggestions = result.get("suggestions") or []
    suggestion = "; ".join(suggestions) if suggestions else None
    return envelope_err(
        error_type,
        result.get("message", "Gremlin query failed"),
        suggestion=suggestion,
        details=result,
        duration_ms=result.get("duration_ms"),
    )


def _execute_gremlin_with_error_handling(
    client, gremlin_query: str, operation_type: str = "read"
) -> dict[str, Any]:
    """执行 Gremlin 查询并做结构化错误处理。

    连接失败、HTTP 错误、语法错误等均返回结构化 dict 而非抛异常，
    便于上层统一处理。区分 401/403/404/500 等状态码给出针对性建议。
    """
    start = time.time()

    try:
        data = client.exec(gremlin_query)
        duration_ms = (time.time() - start) * 1000.0

        try:
            count = len(data)  # type: ignore[arg-type]
        except TypeError:
            count = 1 if data is not None else 0

        return {
            "success": True,
            "data": data,
            "count": count,
            "duration_ms": duration_ms,
            "operation_type": operation_type,
        }

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error_type": "connection_error",
            "message": f"Cannot connect to HugeGraph server at "
            f"{client._url if hasattr(client, '_url') else 'unknown address'}",
            "suggestions": [
                "Check if HugeGraph server is running",
                "Verify the HUGEGRAPH_URL environment variable",
                "Check network connectivity to the server",
            ],
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }

    except requests.exceptions.HTTPError as e:
        status_code = (
            e.response.status_code
            if hasattr(e, "response") and e.response
            else "unknown"
        )

        if status_code == 401:
            error_type = "authentication_error"
            message = "Authentication failed - invalid credentials"
            suggestions = [
                "Check HUGEGRAPH_USER and HUGEGRAPH_PASSWORD environment variables",
                "Verify user permissions in HugeGraph",
            ]
        elif status_code == 403:
            error_type = "authorization_error"
            message = "Authorization failed - insufficient permissions"
            suggestions = [
                "Check if the user has permission to execute Gremlin queries",
                "Verify graph space permissions if using graph spaces",
            ]
        elif status_code == 404:
            error_type = "not_found_error"
            message = "Graph or endpoint not found"
            suggestions = [
                "Check if the graph name is correct",
                "Verify the graph exists in HugeGraph",
            ]
        elif status_code == 500:
            error_type = "server_error"
            # 尝试从响应体中提取 HugeGraph 详细错误信息
            detail_message = ""
            try:
                if hasattr(e, "response") and e.response is not None:
                    error_json = e.response.json()
                    detail_message = error_json.get("exception") or ""
                    if not detail_message:
                        detail_message = (
                            error_json.get("message")
                            or error_json.get("detail")
                            or error_json.get("error")
                            or str(error_json)
                        )
            except Exception:
                pass

            if detail_message:
                message = f"HugeGraph server internal error: {detail_message}"
            else:
                message = "HugeGraph server internal error"
            suggestions = [
                "Check the Gremlin query syntax",
                "Verify all referenced vertex/edge labels exist",
                "Check HugeGraph server logs for details",
                "Ensure the query doesn't violate graph constraints",
            ]
        else:
            error_type = "http_error"
            message = f"HTTP error {status_code}"
            suggestions = ["Check HugeGraph server status", "Verify the request format"]

        return {
            "success": False,
            "error_type": error_type,
            "message": message,
            "status_code": status_code,
            "suggestions": suggestions,
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }

    except ValueError as e:
        return {
            "success": False,
            "error_type": "query_syntax_error",
            "message": f"Gremlin query syntax error: {e!s}",
            "suggestions": [
                "Check Gremlin query syntax",
                "Verify all steps and parameters are valid",
                "Ensure proper use of Gremlin traversal steps",
            ],
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }

    except Exception as e:
        return {
            "success": False,
            "error_type": "unknown_error",
            "message": f"Unexpected error: {e!s}",
            "suggestions": [
                "Check HugeGraph server logs",
                "Verify the query format and parameters",
                "Try a simpler query to test connectivity",
            ],
            "duration_ms": (time.time() - start) * 1000.0,
            "operation_type": operation_type,
        }


def execute_gremlin_read(gremlin_query: str) -> dict[str, Any]:
    """执行只读 Gremlin 查询。

    通过 GremlinPolicy.check_read() 做安全检查，
    拒绝写入类和无法确定的查询，只放行明确安全的遍历。
    返回 {data, total, duration_ms, is_read}。
    """

    decision = check_gremlin_read(gremlin_query)
    if not decision.allowed:
        return envelope_err(
            ErrorType.UNSAFE_GREMLIN,
            decision.reason,
            suggestion=decision.suggestion,
            details={"classification": decision.classification},
        )

    client = _get_read_client()
    result = _execute_gremlin_with_error_handling(client, gremlin_query, "read")

    if result.get("success"):
        duration_ms = result["duration_ms"]
        return envelope_ok(
            {
                "data": result["data"],
                "total": result["count"],
                "duration_ms": duration_ms,
                "is_read": True,
            },
            duration_ms=duration_ms,
        )
    else:
        return _gremlin_error_envelope(result)


def execute_gremlin_write(gremlin_query: str) -> dict[str, Any]:
    """执行 Gremlin 写查询。

    readonly 模式下通过 guard_write 拒绝执行，
    正常模式返回 {success, affected, duration_ms, is_write}。
    """

    violation = guard_write(Capability.DEBUG_WRITE)
    if violation is not None:
        return violation

    client = _get_write_client()
    result = _execute_gremlin_with_error_handling(client, gremlin_query, "write")

    if result.get("success"):
        duration_ms = result["duration_ms"]
        return envelope_ok(
            {
                "affected": result["count"],
                "duration_ms": duration_ms,
                "is_write": True,
            },
            duration_ms=duration_ms,
        )
    else:
        return _gremlin_error_envelope(result)
