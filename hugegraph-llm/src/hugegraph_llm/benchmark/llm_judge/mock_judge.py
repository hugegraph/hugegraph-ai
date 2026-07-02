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

"""Mock LLM judge for offline / testing mode.

Returns fixed scores without calling any LLM. Useful for FakeLLM
offline benchmarking and unit tests.
"""

from typing import Any, Dict

from hugegraph_llm.benchmark.llm_judge.base import LLMJudge


class MockJudge(LLMJudge):
    """Mock judge that returns fixed scores for offline evaluation."""

    def judge(
        self,
        question: str,
        answer: str,
        context: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Return a fixed mock score.

        Returns:
            Dict with score=0.5 and reason='mock'.
        """
        return {"score": 0.5, "reason": "mock"}
