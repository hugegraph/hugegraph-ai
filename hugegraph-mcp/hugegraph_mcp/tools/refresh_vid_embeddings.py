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

from typing import Any

from hugegraph_mcp.envelope import ErrorType, envelope_err, envelope_ok
from hugegraph_mcp.guard import Capability, guard
from hugegraph_mcp.hugegraph_ai_client import post


def refresh_vid_embeddings(confirm: bool = False) -> dict[str, Any]:
    """Manually refresh VID embeddings through HugeGraph-AI."""

    violation = guard(Capability.INDEX_WRITE)
    if violation is not None:
        return violation

    if not confirm:
        return envelope_err(
            ErrorType.CONFIRM_REQUIRED,
            "VID embedding refresh requires confirm=True.",
            suggestion="Pass confirm=True to refresh VID embeddings.",
        )

    ai_result = post("/vid-embeddings/refresh", json={})
    if not ai_result.get("ok"):
        return ai_result

    data = _unwrap_ai_payload(ai_result.get("data"))
    if isinstance(data, dict) and data.get("ok") is False:
        return data

    if not isinstance(data, dict):
        data = {}

    return envelope_ok(
        {
            "added": data.get("added", 0),
            "removed": data.get("removed", 0),
            "summary": data.get("summary"),
        }
    )


def _unwrap_ai_payload(data: Any) -> Any:
    if isinstance(data, dict) and "ok" in data and "data" in data:
        if data.get("ok") is False:
            return data
        return data.get("data")
    return data
