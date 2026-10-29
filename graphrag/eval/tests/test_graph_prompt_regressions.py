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

"""Validate shipped faithfulness examples in the actual assembled prompt."""

import json

import pytest

from hugegraph_llm_eval.prompt import graph_judge_prompt


@pytest.mark.parametrize(
    ("language", "example_heading", "next_heading"),
    (("en", "Expected JSON:\n", "\n\nNow evaluate:"), ("zh", "期望输出：\n", "\n\n现在请评估：")),
)
def test_faithfulness_example_rejects_the_unsupported_two_year_cycle(language, example_heading, next_heading) -> None:
    prompt = graph_judge_prompt("faithfulness", language)
    example = prompt.split(example_heading, 1)[1].split(next_heading, 1)[0]
    verdicts = json.loads(example.replace("{{", "{").replace("}}", "}"))["verdicts"]

    # Item 1 claims a two-year service-replacement cycle. The source only says
    # to rotate tokens every 24 hours or 10,000 requests.
    verdict = next(item for item in verdicts if item["idx"] == 1)
    assert verdict["verdict"] == "No", verdict["reason"]
