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

"""Data models for benchmark results (Pydantic)."""

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SampleResult(BaseModel):
    """Result for a single evaluation sample."""

    model_config = ConfigDict(extra="ignore")

    sample_id: str
    metrics: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    reference_hit: Optional[bool] = None
    # Question-type tier, e.g. "Fact Retrieval" / "Complex Reasoning" /
    # "Contextual Summarize" / "Creative Generation" (GraphRAG-Benchmark).
    # When present on any sample, BenchmarkResult.by_type is populated for
    # tiered reporting. None on untiered runs.
    question_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class BenchmarkResult(BaseModel):
    """Complete benchmark run result."""

    model_config = ConfigDict(extra="ignore")

    overall: Dict[str, float] = Field(default_factory=dict)
    # Per-tier overall scores keyed by SampleResult.question_type. Empty when
    # no sample carries a tier (untiered runs). Mirrors GraphRAG-Benchmark's
    # grouped-by-question_type evaluation, so we can separate Fact Retrieval
    # vs Summarization vs Creative Generation performance instead of collapsing
    # to a single overall number.
    by_type: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    samples: List[SampleResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_timestamp(self) -> "BenchmarkResult":
        if "timestamp" not in self.metadata:
            self.metadata["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the JSON baseline format (meta / overall / by_type / samples)."""
        return {
            "meta": self.metadata,
            "overall": self.overall,
            "by_type": self.by_type,
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkResult":
        """Deserialize from the JSON baseline format."""
        return cls(
            overall=data.get("overall", {}),
            by_type=data.get("by_type", {}),
            samples=[SampleResult(**s) for s in data.get("samples", [])],
            metadata=data.get("meta", {}),
        )

    def compute_overall(self) -> None:
        """Compute overall metrics by averaging per-sample metrics."""
        self.overall = {}
        if not self.samples:
            return
        all_keys: set = set()
        for s in self.samples:
            all_keys.update(s.metrics.keys())
        for key in all_keys:
            values = [s.metrics[key] for s in self.samples if key in s.metrics and s.metrics[key] is not None]
            if values:
                self.overall[key] = round(sum(values) / len(values), 4)

    def compute_by_type(self) -> None:
        """Compute per-tier overall metrics, keyed by ``sample.question_type``.

        Samples without a ``question_type`` are grouped under "Ungrouped".
        No-op when no sample carries a tier, so untiered runs stay unaffected
        and ``by_type`` remains ``{}``.
        """
        if not self.samples or not any(s.question_type for s in self.samples):
            self.by_type = {}
            return
        buckets: Dict[str, List[SampleResult]] = {}
        for s in self.samples:
            key = s.question_type or "Ungrouped"
            buckets.setdefault(key, []).append(s)
        self.by_type = {}
        for tier, group in buckets.items():
            keys: set = set()
            for s in group:
                keys.update(s.metrics.keys())
            tier_overall: Dict[str, float] = {}
            for key in keys:
                values = [s.metrics[key] for s in group if key in s.metrics and s.metrics[key] is not None]
                if values:
                    tier_overall[key] = round(sum(values) / len(values), 4)
            if tier_overall:
                self.by_type[tier] = tier_overall
