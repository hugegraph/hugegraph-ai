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

"""JSON reporter for benchmark results."""

import json
import os

from hugegraph_llm.benchmark.models.result import BenchmarkResult


class JSONReporter:
    """Write BenchmarkResult to a JSON file."""

    @staticmethod
    def report(result: BenchmarkResult, path: str) -> None:
        """Serialize result to JSON and write to *path*.

        Creates parent directories if they do not exist.

        Args:
            result: The benchmark result to persist.
            path: Destination file path.
        """
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
