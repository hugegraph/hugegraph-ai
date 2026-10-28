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

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DeveloperToolingContractTest(unittest.TestCase):
    def _run_quality_script(self, *arguments: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            log_path = directory_path / "uv.log"
            executable = directory_path / "uv"
            executable.write_text(
                '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$UV_LOG"\n',
                encoding="utf-8",
            )
            executable.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{directory_path}{os.pathsep}{env.get('PATH', '')}"
            env["UV_LOG"] = str(log_path)
            subprocess.run(
                ["bash", str(ROOT / "style" / "code_format_and_analysis.sh"), *arguments],
                cwd=ROOT,
                env=env,
                check=True,
            )
            return log_path.read_text(encoding="utf-8").splitlines()

    def test_quality_commands_enable_dev_extra(self) -> None:
        script = (ROOT / "style" / "code_format_and_analysis.sh").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        llm_readme = (ROOT / "hugegraph-llm/README.md").read_text(encoding="utf-8")
        self.assertIn("Run all quality commands from the repository root", llm_readme)
        for command in ("ruff format --check .", "ruff check .", "ty check hugegraph-llm/src/hugegraph_llm"):
            self.assertIn("uv run --extra dev " + command, llm_readme)

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

    def test_default_quality_script_runs_only_blocking_checks(self) -> None:
        self.assertEqual(
            [
                "run --extra dev ruff format .",
                "run --extra dev ruff check .",
            ],
            self._run_quality_script(),
        )

    def test_typecheck_requires_explicit_flag(self) -> None:
        self.assertEqual(
            ["run --extra dev ty check hugegraph-llm/src/hugegraph_llm hugegraph-python-client/src/pyhugegraph"],
            self._run_quality_script("-t"),
        )

    def test_default_codeql_remains_a_separate_required_check(self) -> None:
        ci_doc = (ROOT / "docs" / "quality" / "ci.md").read_text(encoding="utf-8")
        self.assertIn(
            "keep its emitted code-scanning check separately required",
            ci_doc,
        )


if __name__ == "__main__":
    unittest.main()
