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
from hugegraph_mcp.gremlin_safety import classify_gremlin_read_safety
from hugegraph_mcp.gremlin_tools import execute_gremlin_read
from hugegraph_mcp.hugegraph_ai_client import post


def generate_gremlin(
    query: str,
    execute: bool = False,
    output_types: list[str] | None = None,
) -> dict[str, Any]:
    """Generate Gremlin from natural language via HugeGraph-AI.

    By default this tool only returns generated Gremlin and safety metadata.
    Automatic execution is allowed only for confidently read-only traversals.
    """

    ai_result = post("/text2gremlin", json={"query": query})
    if not ai_result.get("ok"):
        return ai_result

    ai_data = ai_result.get("data") or {}
    gremlin = ai_data.get("gremlin")
    template_gremlin = ai_data.get("template_gremlin")
    raw_gremlin = ai_data.get("raw_gremlin")
    requires_index = ai_data.get("requires_index", False)
    assumptions = ai_data.get("assumptions")

    safety = classify_gremlin_read_safety(gremlin)
    is_readonly = safety == "safe"
    risk_level = _risk_level(safety)

    data = {
        "gremlin": gremlin,
        "template_gremlin": template_gremlin,
        "raw_gremlin": raw_gremlin,
        "is_readonly": is_readonly,
        "risk_level": risk_level,
        "requires_index": requires_index,
        "assumptions": assumptions,
        "executed": False,
        "execution_result": None,
    }

    if not execute:
        return envelope_ok(data)

    if not is_readonly:
        return envelope_err(
            ErrorType.UNSAFE_GREMLIN,
            "Generated Gremlin is not safe to execute automatically",
            details={
                "classification": safety,
                "gremlin": gremlin,
                "risk_level": risk_level,
            },
        )

    data["executed"] = True
    data["execution_result"] = execute_gremlin_read(gremlin)
    return envelope_ok(data)


def _risk_level(safety: str) -> str:
    if safety == "safe":
        return "low"
    if safety == "unsafe":
        return "high"
    return "medium"
