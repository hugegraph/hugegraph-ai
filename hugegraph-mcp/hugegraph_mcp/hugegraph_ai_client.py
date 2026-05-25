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

import time
from typing import Any

import requests

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok


def request(
    method: str,
    path: str,
    *,
    cfg: MCPConfig | None = None,
    json: Any = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Call HugeGraph-AI and return a standardized envelope."""

    start = time.time()
    cfg = cfg or MCPConfig.from_env()
    method = method.upper()
    url = _build_url(cfg.ai_url, path)

    if not cfg.allow_ai:
        return _ai_error(
            "AI calls are disabled",
            duration_ms=_duration_ms(start),
            details={"method": method, "url": url},
        )

    try:
        kwargs: dict[str, Any] = {
            "params": params,
            "headers": headers,
            "timeout": cfg.timeout_seconds,
        }
        if json is not None:
            kwargs["json"] = json
        if cfg.password:
            kwargs["auth"] = (cfg.user, cfg.password)

        response = requests.request(method, url, **kwargs)
        response.raise_for_status()
        data = response.json()
        return envelope_ok(data, duration_ms=_duration_ms(start))
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        return _ai_error(
            _exception_message("HugeGraph-AI is unavailable", exc),
            duration_ms=_duration_ms(start),
            retryable=True,
            details={"method": method, "url": url},
        )
    except requests.exceptions.HTTPError as exc:
        status_code = _status_code(exc)
        if isinstance(status_code, int) and 400 <= status_code < 500:
            return envelope_err(
                ErrorType.AUTHORIZATION_FAILED,
                _exception_message("HugeGraph-AI authorization failed", exc),
                retryable=False,
                details={"method": method, "url": url, "status_code": status_code},
                duration_ms=_duration_ms(start),
            )
        return _ai_error(
            _exception_message("HugeGraph-AI is unavailable", exc),
            duration_ms=_duration_ms(start),
            retryable=True,
            details={"method": method, "url": url, "status_code": status_code},
        )
    except ValueError as exc:
        return _ai_error(
            _exception_message("HugeGraph-AI returned invalid JSON", exc),
            duration_ms=_duration_ms(start),
            details={"method": method, "url": url},
        )
    except requests.exceptions.RequestException as exc:
        return _ai_error(
            _exception_message("HugeGraph-AI request failed", exc),
            duration_ms=_duration_ms(start),
            retryable=True,
            details={"method": method, "url": url},
        )


def get(
    path: str,
    *,
    cfg: MCPConfig | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return request("GET", path, cfg=cfg, params=params, headers=headers)


def post(
    path: str,
    *,
    cfg: MCPConfig | None = None,
    json: Any = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    return request("POST", path, cfg=cfg, json=json, params=params, headers=headers)


def health_check(*, cfg: MCPConfig | None = None) -> dict[str, Any]:
    """Best-effort HugeGraph-AI readiness check.

    Some HugeGraph-AI deployments expose no /health route. Prefer a lightweight
    thin API endpoint and fall back to OpenAPI metadata before reporting the
    service unavailable.
    """

    attempts: list[str] = []
    last_result: dict[str, Any] | None = None
    for path in ("/graph-index-info", "/openapi.json"):
        result = get(path, cfg=cfg)
        if result.get("ok"):
            data = result.get("data")
            if isinstance(data, dict):
                result["data"] = {
                    "status": "available",
                    "health_endpoint": path,
                    **data,
                }
            else:
                result["data"] = {
                    "status": "available",
                    "health_endpoint": path,
                    "response": data,
                }
            if attempts:
                result["warnings"] = [*result.get("warnings", []), *attempts]
            return result

        last_result = result
        error = result.get("error") or {}
        details = error.get("details") or {}
        status_code = details.get("status_code")
        attempts.append(f"{path}: {error.get('message', 'unavailable')}")
        if status_code in {401, 403}:
            return result

    if last_result is not None and attempts:
        last_result["warnings"] = [*last_result.get("warnings", []), *attempts]
    return last_result or get("/openapi.json", cfg=cfg)


def _build_url(base_url: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _duration_ms(start: float) -> float:
    return (time.time() - start) * 1000.0


def _status_code(exc: requests.exceptions.HTTPError) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _exception_message(prefix: str, exc: Exception) -> str:
    message = str(exc).strip()
    return f"{prefix}: {message}" if message else prefix


def _ai_error(
    message: str,
    *,
    duration_ms: float,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.HUGEGRAPH_AI_UNAVAILABLE,
        message,
        retryable=retryable,
        details=details,
        duration_ms=duration_ms,
    )
