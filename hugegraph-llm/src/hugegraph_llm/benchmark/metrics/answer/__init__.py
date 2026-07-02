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

"""Answer metrics for benchmark evaluation."""

from hugegraph_llm.benchmark.metrics.answer.answer_correctness import AnswerCorrectness
from hugegraph_llm.benchmark.metrics.answer.coverage import Coverage
from hugegraph_llm.benchmark.metrics.answer.exact_match import ExactMatch
from hugegraph_llm.benchmark.metrics.answer.faithfulness import Faithfulness
from hugegraph_llm.benchmark.metrics.answer.rouge_l import RougeL
from hugegraph_llm.benchmark.metrics.answer.token_f1 import TokenF1

__all__ = [
    "TokenF1",
    "ExactMatch",
    "RougeL",
    "Faithfulness",
    "AnswerCorrectness",
    "Coverage",
]
