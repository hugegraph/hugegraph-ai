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

from enum import Enum
from typing import Any
from uuid import uuid4

from hugegraph_mcp.config import MCPConfig


class ErrorType(str, Enum):
    CONNECTION_FAILED = "CONNECTION_FAILED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    READONLY_VIOLATION = "READONLY_VIOLATION"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
    NO_INDEX = "NO_INDEX"
    UNSAFE_GREMLIN = "UNSAFE_GREMLIN"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    INVALID_GRAPH_DATA = "INVALID_GRAPH_DATA"
    HUGEGRAPH_AI_UNAVAILABLE = "HUGEGRAPH_AI_UNAVAILABLE"
    FLOW_EXECUTION_FAILED = "FLOW_EXECUTION_FAILED"
    LLM_FAILED = "LLM_FAILED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED_SQL_SOURCE = "UNSUPPORTED_SQL_SOURCE"
    UNSAFE_SQL = "UNSAFE_SQL"
    SQL_SOURCE_NOT_FOUND = "SQL_SOURCE_NOT_FOUND"


def generate_request_id() -> str:
    return f"req-{uuid4().hex[:12]}"


def build_meta(
    *,
    duration_ms: float | int | None = None,
    request_id: str | None = None,
    graph: str | None = None,
    graphspace: str | None = None,
    readonly: bool | None = None,
    extra_meta: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    cfg = MCPConfig.from_env()
    meta = {
        "request_id": request_id or generate_request_id(),
        "graph": cfg.graph if graph is None else graph,
        "graphspace": cfg.graphspace if graphspace is None else graphspace,
        "readonly": cfg.readonly if readonly is None else readonly,
    }

    if duration_ms is not None:
        meta["duration_ms"] = duration_ms
    if extra_meta:
        meta.update(extra_meta)
    if kwargs:
        meta.update(kwargs)

    return meta


def envelope_ok(
    data: Any = None,
    *,
    duration_ms: float | int | None = None,
    warnings: list[str] | tuple[str, ...] | None = None,
    next_actions: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    request_id: str | None = None,
    graph: str | None = None,
    graphspace: str | None = None,
    readonly: bool | None = None,
    **meta_fields: Any,
) -> dict[str, Any]:
    envelope_meta = build_meta(
        duration_ms=duration_ms,
        request_id=request_id,
        graph=graph,
        graphspace=graphspace,
        readonly=readonly,
        extra_meta=meta,
        **meta_fields,
    )
    return {
        "ok": True,
        "data": data,
        "error": None,
        "warnings": list(warnings or []),
        "next_actions": list(next_actions or []),
        "meta": envelope_meta,
    }


def envelope_err(
    error_type: ErrorType | str,
    message: str,
    *,
    suggestion: str | None = None,
    retryable: bool = False,
    source: str = "hugegraph-mcp",
    details: Any = None,
    duration_ms: float | int | None = None,
    warnings: list[str] | tuple[str, ...] | None = None,
    next_actions: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    request_id: str | None = None,
    graph: str | None = None,
    graphspace: str | None = None,
    readonly: bool | None = None,
    **meta_fields: Any,
) -> dict[str, Any]:
    error_value = (
        error_type.value if isinstance(error_type, ErrorType) else str(error_type)
    )
    error: dict[str, Any] = {
        "type": error_value,
        "message": message,
        "suggestion": suggestion,
        "retryable": retryable,
        "source": source,
        "details": details if details is not None else {},
    }

    envelope_meta = build_meta(
        duration_ms=duration_ms,
        request_id=request_id,
        graph=graph,
        graphspace=graphspace,
        readonly=readonly,
        extra_meta=meta,
        **meta_fields,
    )
    return {
        "ok": False,
        "data": None,
        "error": error,
        "warnings": list(warnings or []),
        "next_actions": list(next_actions or []),
        "meta": envelope_meta,
    }


make_ok_envelope = envelope_ok
make_err_envelope = envelope_err
ok_envelope = envelope_ok
err_envelope = envelope_err
ok = envelope_ok
err = envelope_err
