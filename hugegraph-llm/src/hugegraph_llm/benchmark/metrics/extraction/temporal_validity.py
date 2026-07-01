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

"""Temporal validity metrics for extracted graphs.

Checks whether temporal attributes (years, dates, times) fall within
reasonable ranges and are parseable.
"""

import re
from datetime import datetime
from typing import Any, Dict, List

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import MetricRegistry

# Keywords that indicate a property is temporal
_TEMPORAL_KEYWORDS = frozenset(
    {
        "year",
        "date",
        "time",
        "month",
        "day",
        "start_date",
        "end_date",
        "birth_date",
        "death_date",
        "created_at",
        "updated_at",
        "timestamp",
        "founded",
        "established",
        "born",
        "died",
        "年",
        "月",
        "日",
        "时间",
        "日期",
        "年份",
    }
)

# Year range considered valid
_MIN_YEAR = 1900
_MAX_YEAR = 2030

# Common date formats to try parsing
_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y%m%d",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]


def _is_temporal_key(key: str) -> bool:
    """Check if a property key indicates a temporal attribute."""
    lower_key = key.lower().strip()
    # Direct match
    if lower_key in _TEMPORAL_KEYWORDS:
        return True
    # Substring match
    for keyword in _TEMPORAL_KEYWORDS:
        if keyword in lower_key:
            return True
    return False


def _validate_temporal_value(value: Any) -> bool:
    """Check if a temporal value is valid.

    Tries multiple interpretations:
    1. Numeric year in [_MIN_YEAR, _MAX_YEAR]
    2. Parseable date string
    3. Timestamp-like numeric value
    """
    str_val = str(value).strip()
    if not str_val:
        return False

    # Try as pure numeric (year)
    try:
        num = float(str_val)
        if _MIN_YEAR <= num <= _MAX_YEAR:
            return True
        # Could be a Unix timestamp; avoid treating small integers as dates.
        if 946684800 <= num <= 4102444800:  # 2000-01-01 to 2100-01-01 UTC
            return True
        return False
    except (ValueError, OverflowError):
        pass

    # Try common date formats
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(str_val, fmt)
            return _MIN_YEAR <= dt.year <= _MAX_YEAR
        except ValueError:
            continue

    # Try extracting a year from text like "2020年" or "circa 1995"
    year_match = re.search(r"\b(\d{4})\b", str_val)
    if year_match:
        year = int(year_match.group(1))
        return _MIN_YEAR <= year <= _MAX_YEAR

    return False


@MetricRegistry.register
class TemporalValidity(BaseMetric):
    """Temporal validity check for extracted graph properties.

    Scans vertex properties for temporal attributes and validates
    that their values fall within reasonable ranges.

    Metrics:
    - temporal_valid_rate: Fraction of valid temporal attributes
    - num_temporal_attrs: Total number of temporal attributes detected

    Registered name: ``temporal_validity``
    """

    name: str = "temporal_validity"
    requires_llm: bool = False

    def calculate(
        self,
        prediction: Any,
        reference: Any = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Calculate temporal validity metrics.

        Args:
            prediction: Dict with ``vertices`` list. Each vertex may have
                        a ``properties`` dict containing temporal attributes.
            reference: Unused.

        Returns:
            Dict with temporal_valid_rate and num_temporal_attrs.
        """
        if not isinstance(prediction, dict):
            return {"temporal_valid_rate": 1.0, "num_temporal_attrs": 0.0}

        vertices: List[Dict[str, Any]] = prediction.get("vertices", [])
        if not isinstance(vertices, list):
            vertices = []

        total_temporal = 0
        valid_temporal = 0

        for v in vertices:
            props = v.get("properties")
            if not isinstance(props, dict):
                continue

            for key, value in props.items():
                if _is_temporal_key(key):
                    total_temporal += 1
                    if _validate_temporal_value(value):
                        valid_temporal += 1

        if total_temporal == 0:
            return {"temporal_valid_rate": 1.0, "num_temporal_attrs": 0.0}

        rate = valid_temporal / total_temporal

        return {
            "temporal_valid_rate": round(rate, 4),
            "num_temporal_attrs": float(total_temporal),
        }
