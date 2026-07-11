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

"""Small helpers for dry-run -> plan_hash -> confirm write workflows."""

from typing import Any

from hugegraph_mcp.envelope import ErrorType, envelope_err


def mark_readonly_preview(
    payload: dict[str, Any],
    *,
    warning: str,
    next_action: str,
) -> tuple[dict[str, Any], list[str], list[str]]:
    payload["confirmable"] = False
    payload["readonly_preview_only"] = True
    return payload, [warning], [next_action]


def confirm_required_error(
    *,
    message: str,
    suggestion: str,
    source: str | None = None,
) -> dict[str, Any]:
    return envelope_err(
        ErrorType.CONFIRM_REQUIRED,
        message,
        suggestion=suggestion,
        source=source,
    )


def plan_hash_error(
    *,
    error_type: ErrorType | None,
    details: dict[str, Any],
    mismatch_message: str,
    expired_message: str | None = None,
    suggestion: str,
    source: str | None = None,
) -> dict[str, Any]:
    resolved_error_type = error_type or ErrorType.PLAN_HASH_MISMATCH
    message = (
        expired_message
        if resolved_error_type == ErrorType.PLAN_EXPIRED and expired_message
        else mismatch_message
    )
    return envelope_err(
        resolved_error_type,
        message,
        suggestion=suggestion,
        source=source,
        details=details,
    )
