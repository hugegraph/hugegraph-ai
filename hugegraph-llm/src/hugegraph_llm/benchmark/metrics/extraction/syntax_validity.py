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

"""Syntax validity metrics for graph extraction pipeline.

Evaluates whether LLM raw responses were successfully parsed into
structured JSON and optionally whether the parsed results were
successfully loaded into the graph database.
"""

from typing import Any, Dict, List, Optional

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry


@MetricRegistry.register
class SyntaxValidity(BaseMetric):
    """Syntax validity metrics for extraction pipeline outputs.

    Expects prediction as a dict with:
    - ``raw_responses``: List[str] - raw LLM output strings
    - ``parse_results``: List[Optional[Dict]] - parsed results (None = parse failure)

    Optionally via kwargs:
    - ``db_load_results``: List[bool] - whether each parsed result loaded into DB

    Metrics:
    - json_parse_rate: fraction of responses that parsed successfully
    - load_to_db_success: fraction of loads that succeeded (0.0 if no data)

    Registered name: ``syntax_validity``
    """

    name: str = "syntax_validity"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate syntax validity metrics.

        Args:
            prediction: Dict with ``raw_responses`` and ``parse_results``.
            reference: Unused.
            **kwargs: Optional ``db_load_results`` (List[bool]).

        Returns:
            Dict with json_parse_rate and load_to_db_success.
        """
        if not isinstance(prediction, dict):
            return {"json_parse_rate": 0.0, "load_to_db_success": 0.0}

        parse_results: List[Optional[Dict[str, Any]]] = prediction.get("parse_results", [])
        if not isinstance(parse_results, list):
            parse_results = []

        # --- json_parse_rate ---
        if parse_results:
            success_count = sum(1 for r in parse_results if r is not None)
            json_parse_rate = success_count / len(parse_results)
        else:
            json_parse_rate = 0.0

        # --- load_to_db_success ---
        db_load_results: Optional[List[bool]] = kwargs.get("db_load_results")
        if isinstance(db_load_results, list) and db_load_results:
            load_success = sum(1 for r in db_load_results if r)
            load_to_db_success = load_success / len(db_load_results)
        else:
            load_to_db_success = 0.0

        return {
            "json_parse_rate": round(json_parse_rate, 4),
            "load_to_db_success": round(load_to_db_success, 4),
        }
