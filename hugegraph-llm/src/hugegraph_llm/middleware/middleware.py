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

import contextvars
import time
import uuid
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from hugegraph_llm.utils.log import log


# Phase 3 P3-T3: trace_id propagated via contextvars so async tasks spawned
# inside a route (incl. sub-tasks awaited via asyncio.to_thread) inherit it
# without requiring explicit threading. Streaming routes that need trace_id in
# error payloads can call ``get_trace_id()`` instead of generating their own.
_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("hugegraph_llm_trace_id", default=None)


def get_trace_id() -> Optional[str]:
    """Return the current request's trace_id, or None outside a request context."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> contextvars.Token:
    """Bind a trace_id to the current context. Caller is responsible for resetting
    via the returned token if it is not the request entry-point."""
    return _trace_id_var.set(trace_id)


# TODO: we could use middleware(AOP) in the future (dig out the lifecycle of gradio & fastapi)
class UseTimeMiddleware(BaseHTTPMiddleware):
    """Middleware to add process time + trace_id to response headers and logs.

    Phase 3 P3-T3:
    - Generates / propagates ``X-Trace-Id`` per request (honoring an inbound header
      when supplied so it survives across services).
    - Stores the id in a ``ContextVar`` so async sub-tasks inherit it; the
      streaming route's existing ``X-Trace-Id`` header takes precedence when set
      (it owns the SSE error payload contract).
    - ``StreamingResponse`` is **never** consumed here — ``BaseHTTPMiddleware``
      passes it through untouched once ``call_next`` returns.
    """

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        # Honor inbound trace id (cross-service propagation), else mint one.
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        token = _trace_id_var.set(trace_id)
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            _trace_id_var.reset(token)

        process_time = (time.perf_counter() - start_time) * 1000  # ms
        unit = "ms"
        if process_time > 1000:
            process_time /= 1000
            unit = "s"

        response.headers["X-Process-Time"] = f"{process_time:.2f} {unit}"
        # Don't override trace id set by streaming route (it owns the SSE error
        # contract); only stamp it when the route hasn't already.
        response.headers.setdefault("X-Trace-Id", trace_id)
        log.info(
            "Request process time: %.2f %s, code=%d, trace_id=%s",
            process_time,
            unit,
            response.status_code,
            trace_id,
        )
        log.info(
            "%s - Args: %s, IP: %s, URL: %s",
            request.method,
            request.query_params,
            request.client.host if request.client else "-",
            request.url,
        )
        return response
