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

"""Metric registry for automatic discovery and lookup.

Design: Registry pattern - metrics self-register via decorator or explicit call.
Runners look up metrics by name to compose evaluation pipelines.

The registry dict is stored at module level (_METRIC_REGISTRY) rather than
as a class variable to avoid mutable-default-argument pitfalls with
class-level dicts shared across inheritance hierarchies.
"""

from typing import Dict, List, Optional, Type

from hugegraph_llm.benchmark.metrics.base import BaseMetric

# Module-level registry to avoid mutable class-variable issues.
_METRIC_REGISTRY: Dict[str, Type[BaseMetric]] = {}


class MetricRegistry:
    """Central registry for all benchmark metrics."""

    @classmethod
    def register(cls, metric_class: Type[BaseMetric]) -> Type[BaseMetric]:
        """Register a metric class. Can be used as a decorator."""
        if not metric_class.name:
            raise ValueError(f"Metric class {metric_class.__name__} must set 'name' attribute")
        _METRIC_REGISTRY[metric_class.name] = metric_class
        return metric_class

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseMetric]]:
        return _METRIC_REGISTRY.get(name)

    @classmethod
    def create(cls, name: str) -> BaseMetric:
        """Create a metric instance by name."""
        metric_class = _METRIC_REGISTRY.get(name)
        if metric_class is None:
            available = ", ".join(sorted(_METRIC_REGISTRY.keys()))
            raise KeyError(f"Unknown metric '{name}'. Available: {available}")
        return metric_class()

    @classmethod
    def list_metrics(cls) -> List[str]:
        return sorted(_METRIC_REGISTRY.keys())

    @classmethod
    def list_by_category(cls, category: str) -> List[str]:
        """List metrics whose name starts with the given category prefix."""
        return sorted(name for name in _METRIC_REGISTRY if name.startswith(category))
