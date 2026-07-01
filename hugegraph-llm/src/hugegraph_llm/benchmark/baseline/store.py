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

"""Baseline store for persisting and loading benchmark results."""

import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from hugegraph_llm.benchmark.models.result import BenchmarkResult


class BaselineStore:
    """Save, load, and list benchmark baseline results as JSON files."""

    @staticmethod
    def _get_git_commit() -> str:
        """Get current git commit hash, or 'unknown' if unavailable."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    @classmethod
    def save(cls, result: BenchmarkResult, path: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Save a BenchmarkResult to a JSON file.

        Automatically records timestamp, git_commit, model, temperature, seed
        in metadata. Creates parent directories if they don't exist.

        Args:
            result: The benchmark result to save.
            path: File path for the JSON output.
            metadata: Additional metadata to merge into result.metadata.
        """
        # Build auto-metadata
        auto_meta: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_commit": cls._get_git_commit(),
        }
        # Pull common fields from result.metadata if present
        for key in ("model", "temperature", "seed"):
            if key in result.metadata:
                auto_meta[key] = result.metadata[key]

        # Merge user-provided metadata (takes precedence)
        if metadata:
            auto_meta.update(metadata)

        # Update result metadata
        result.metadata.update(auto_meta)

        # Ensure directory exists
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> BenchmarkResult:
        """Load a BenchmarkResult from a JSON file.

        Args:
            path: Path to the JSON file.

        Returns:
            Reconstructed BenchmarkResult.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return BenchmarkResult.from_dict(data)

    @classmethod
    def list_baselines(cls, directory: str) -> List[Dict[str, Any]]:
        """List all baseline JSON files in a directory with their meta info.

        Args:
            directory: Directory to scan for .json files.

        Returns:
            List of dicts, each containing filename and metadata fields.
        """
        baselines: List[Dict[str, Any]] = []
        if not os.path.isdir(directory):
            return baselines

        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(directory, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("meta", {})
                entry: Dict[str, Any] = {"filename": fname}
                entry.update(meta)
                baselines.append(entry)
            except (json.JSONDecodeError, OSError):
                continue

        return baselines
