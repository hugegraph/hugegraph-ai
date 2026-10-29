# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A custom validator participates in the existing repair loop."""

import json
from copy import deepcopy

from _fixtures import GRAPH, PASS_REVIEW, SCHEMA, TEXT

from hugegraph_llm_sdk import FunctionModel, GraphPrompts, Issue, extract_graph


def source_company_rule(graph, schema, text):
    del schema
    return [
        Issue(
            path=f"vertices[{index}].properties.name",
            message="The company name must appear in the supplied text.",
            evidence=text,
        )
        for index, vertex in enumerate(graph["vertices"])
        if vertex.get("label") == "company" and vertex["properties"].get("name", "") not in text
    ]


def main():
    incorrect_graph = deepcopy(GRAPH)
    incorrect_graph["vertices"][1]["properties"]["name"] = "Unknown Company"
    responses = iter(json.dumps(value) for value in (incorrect_graph, GRAPH, PASS_REVIEW))

    result = extract_graph(
        TEXT,
        schema=SCHEMA,
        model=FunctionModel(generate=lambda prompt: next(responses)),
        prompts=GraphPrompts(extract="Extract only employment facts supported by the source text. Return JSON."),
        validators=[source_company_rule],
    )
    assert result.status == "succeeded"
    assert result.chunks[0].fixes_used == 1
    assert result.chunks[0].llm_calls == 3
    assert result.graph["vertices"][1]["properties"]["name"] == "Acme"
    print("Custom validation triggered one repair; the corrected graph passed review.")  # noqa: T201


if __name__ == "__main__":
    main()
