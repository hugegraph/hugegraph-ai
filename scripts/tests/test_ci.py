# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("ci", SCRIPTS / "ci.py")
assert spec is not None and spec.loader is not None
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class TestCISelection(unittest.TestCase):
    def assert_modules(self, paths, expected):
        selected = ci.select(paths)
        self.assertEqual(set(expected), {key for key in ci.MODULES if selected[key]})

    def test_docs_only_skip_runtime_and_security_jobs(self):
        flags = ci.select(["README.md", "hugegraph-mcp/README.zh-CN.md", "hugegraph-llm/docs/config.md"])
        self.assertFalse(any(flags.values()))

    def test_client_changes_test_downstream_callers(self):
        self.assert_modules(["hugegraph-python-client/src/pyhugegraph/client.py"], {"client", "llm", "mcp"})

    def test_module_changes_are_isolated(self):
        self.assert_modules(["hugegraph-llm/src/hugegraph_llm/config/hugegraph_config.py"], {"llm"})
        self.assert_modules(["hugegraph-mcp/tests/contracts/write_confirmation_v2.json"], {"mcp"})
        self.assert_modules(["docker/Dockerfile.llm"], {"llm"})

    def test_shared_config_and_workflows_do_not_skip_tests(self):
        for path in ("pyproject.toml", "scripts/ci.py", ".github/actions/setup-python-env/action.yml"):
            with self.subTest(path=path):
                self.assert_modules([path], {"client", "llm", "mcp"})
        self.assert_modules([".github/workflows/hugegraph-llm.yml"], {"llm"})

    def test_dependency_review_requires_dependency_changes(self):
        self.assertFalse(ci.select(["hugegraph-mcp/hugegraph_mcp/server.py"])["dependencies"])
        self.assertTrue(ci.select(["hugegraph-mcp/pyproject.toml"])["dependencies"])

    def test_full_and_on_demand_selections(self):
        self.assertTrue(all(ci.select([], full=True).values()))
        selected = ci.select([], test_set="codeql")
        self.assertEqual({"codeql"}, {key for key, value in selected.items() if value})

    def test_deleted_and_renamed_files_are_selected_from_real_git_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args], text=True).strip()

            git("init", "-q")
            git("config", "user.email", "ci-test@example.invalid")
            git("config", "user.name", "CI Test")
            source = root / "hugegraph-python-client" / "client.py"
            source.parent.mkdir()
            source.write_text("original\n")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            git("mv", "hugegraph-python-client/client.py", "README.md")
            git("commit", "-qm", "move")
            original_run = ci.subprocess.run
            with patch.object(ci.subprocess, "run", side_effect=lambda *a, **kw: original_run(*a, cwd=root, **kw)):
                paths = ci.changed_paths({"before": base}, "push")
            self.assertIn("hugegraph-python-client/client.py", paths)
            self.assert_modules(paths, {"client", "llm", "mcp"})


if __name__ == "__main__":
    unittest.main()
