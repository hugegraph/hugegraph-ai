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

"""Design, edit, validate and extract without a model service or database."""

import json

from _fixtures import GRAPH, PASS_REVIEW, SCHEMA, TEXT

from hugegraph_llm_sdk import FunctionModel, design_schema, extract_graph, validate_schema


def main():
    responses = iter(json.dumps(value) for value in (SCHEMA, GRAPH, PASS_REVIEW))
    model = FunctionModel(generate=lambda prompt: next(responses))

    draft = design_schema(TEXT, questions=["Who works for which company?"], model=model)
    assert not draft.issues

    # A caller owns the schema and can edit it before extraction.
    draft.schema["propertykeys"].append({"name": "role", "data_type": "TEXT", "cardinality": "SINGLE"})
    draft.schema["vertexlabels"][0]["properties"].append("role")
    draft.schema["vertexlabels"][0]["nullable_keys"].append("role")
    assert not validate_schema(draft.schema)

    result = extract_graph(TEXT, schema=draft.schema, model=model)
    assert result.status == "succeeded"
    assert result.chunks[0].status == "final"
    assert len(result.graph["vertices"]) == 2
    assert len(result.graph["edges"]) == 1
    print(json.dumps(result.graph, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
