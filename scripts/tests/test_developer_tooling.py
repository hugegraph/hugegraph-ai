#!/usr/bin/env python3

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

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DeveloperToolingContractTest(unittest.TestCase):
    def test_quality_commands_enable_dev_extra(self) -> None:
        script = (ROOT / "style" / "code_format_and_analysis.sh").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        expected_script_commands = (
            "uv run --extra dev ruff format .",
            "uv run --extra dev ruff check .",
            ("uv run --extra dev ty check hugegraph-llm/src/hugegraph_llm hugegraph-python-client/src/pyhugegraph"),
        )
        for command in expected_script_commands:
            self.assertIn(command, script)

        expected_readme_commands = (
            "uv run --extra dev ruff format --check .",
            "uv run --extra dev ruff check .",
            ("uv run --extra dev ty check hugegraph-llm/src/hugegraph_llm hugegraph-python-client/src/pyhugegraph"),
            "uv run --extra dev pre-commit install",
        )
        for command in expected_readme_commands:
            self.assertIn(command, readme)

    def test_default_codeql_remains_a_separate_required_check(self) -> None:
        ci_doc = (ROOT / "docs" / "quality" / "ci.md").read_text(encoding="utf-8")
        self.assertIn(
            "keep its emitted code-scanning check separately required",
            ci_doc,
        )


if __name__ == "__main__":
    unittest.main()
