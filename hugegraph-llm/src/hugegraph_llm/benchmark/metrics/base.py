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

"""Base metric class for all benchmark metrics.

Design: Strategy pattern - each metric implements the `calculate` interface.
Metrics are registered via MetricRegistry and invoked by name from runners.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseMetric(ABC):
    """Abstract base class for all benchmark metrics.

    Subclasses must implement `calculate()` and set `name` and `requires_llm`.
    """

    name: str = ""
    requires_llm: bool = False

    @abstractmethod
    def calculate(self, prediction: Any, reference: Any, **kwargs: Any) -> Dict[str, float]:
        """Calculate metric scores for a single sample.

        Args:
            prediction: The system output (candidate).
            reference: The gold standard (expected output).
            **kwargs: Additional context (e.g., schema, question text).

        Returns:
            Dict mapping metric name to score (float 0-1 where applicable).
        """

    def aggregate(self, sample_scores: list) -> Dict[str, float]:
        """Aggregate per-sample scores into overall scores.

        Default: mean of all non-None values per metric key.
        Override for metrics needing weighted or non-mean aggregation.
        """
        if not sample_scores:
            return {}
        all_keys: set = set()
        for s in sample_scores:
            all_keys.update(s.keys())
        result = {}
        for key in all_keys:
            values = [s[key] for s in sample_scores if key in s and s[key] is not None]
            if values:
                result[key] = round(sum(values) / len(values), 4)
        return result
