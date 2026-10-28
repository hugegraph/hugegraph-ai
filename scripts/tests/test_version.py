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

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tomllib

from scripts import version


class TestReleaseVersion(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        paths = ["pyproject.toml", *(f"{module}/pyproject.toml" for module in version.MODULES)]
        for relative in (*paths, *version.DOCS, *version.DEPLOYMENT):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(version.ROOT / relative, target)
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def run_command(self, *args):
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return version.main(list(args), root=self.root)

    def bump_root(self):
        path = self.root / "pyproject.toml"
        current = version.release_config(self.root)["version"]
        path.write_text(path.read_text().replace(f'version = "{current}"', 'version = "1.9.2"'))

    def test_root_bump_syncs_packages_dependency_and_deployment(self):
        self.bump_root()
        self.assertEqual(0, self.run_command("sync"))
        for module in version.MODULES:
            project = tomllib.loads((self.root / module / "pyproject.toml").read_text())["project"]
            self.assertEqual("1.9.2", project["version"])
            if module == "hugegraph-mcp":
                self.assertIn("hugegraph-python>=1.9.2,<2", project["dependencies"])
        self.assertIn('appVersion: "1.9.2"', (self.root / version.DEPLOYMENT[0]).read_text())
        self.assertIn("hugegraph/rag:1.9.2", (self.root / version.DEPLOYMENT[2]).read_text())
        self.assertIn("hugegraph-mcp@1.9.2", (self.root / version.DOCS[0]).read_text())
        self.assertEqual(0, self.run_command("check"))

    def test_check_reports_drift_without_writing(self):
        self.bump_root()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(1, self.run_command("check"))
        self.assertIn("hugegraph-mcp/pyproject.toml", self.stdout.getvalue())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_sync_is_idempotent(self):
        self.assertEqual(0, self.run_command("sync"))
        self.stdout.truncate(0)
        self.stdout.seek(0)
        self.assertEqual(0, self.run_command("sync"))
        self.assertEqual("", self.stdout.getvalue())

    def test_ci_tool_minimums_follow_root_dev_requirements(self):
        path = self.root / "pyproject.toml"
        previous = version.release_config(self.root)["ruff-version"]
        previous_ty = version.release_config(self.root)["ty-version"]
        path.write_text(path.read_text().replace(f"ruff>={previous}", "ruff>=0.17.99"))
        self.assertEqual("0.17.99", version.release_config(self.root)["ruff-version"])
        self.assertEqual(previous_ty, version.release_config(self.root)["ty-version"])

    def test_tool_versions_must_remain_open_ended_requirements(self):
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text().replace("ruff>=", "ruff=="))
        self.assertEqual(1, self.run_command("get", "ruff-version"))
        self.assertIn("Declare ruff with >=", self.stderr.getvalue())

    def test_history_minimums_and_protocol_versions_are_preserved(self):
        self.bump_root()
        readme = self.root / version.DOCS[0]
        historical = "\nMigration from `1.7.1`; Server >= 1.7.0; protocol_version=1.\n"
        readme.write_text(readme.read_text() + historical)
        self.assertEqual(0, self.run_command("sync"))
        self.assertIn(historical, readme.read_text())

    def test_invalid_metadata_fails_before_any_write(self):
        self.bump_root()
        path = self.root / "hugegraph-mcp/pyproject.toml"
        path.write_text(path.read_text().replace('version = "', 'missing_version = "'))
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(1, self.run_command("sync"))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_get_reads_root_config_without_modifying_metadata(self):
        self.bump_root()
        self.assertEqual(0, self.run_command("get", "version"))
        self.assertEqual("1.9.2\n", self.stdout.getvalue())

    def copy_scripts(self, *names):
        (self.root / "scripts").mkdir(exist_ok=True)
        for name in ("version.py", *names):
            shutil.copyfile(version.ROOT / "scripts" / name, self.root / "scripts" / name)

    def test_build_script_reads_root_tag_from_another_directory(self):
        self.bump_root()
        self.run_command("sync")
        self.copy_scripts("build_llm_image.sh")
        docker = self.root / "bin" / "docker"
        docker.parent.mkdir()
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        docker.chmod(0o755)
        result = subprocess.run(
            ["bash", str(self.root / "scripts/build_llm_image.sh")],
            cwd=self.root / "bin",
            env={
                **os.environ,
                "PATH": str(docker.parent) + os.pathsep + os.environ["PATH"],
                "PYTHON_FOR_RELEASE": sys.executable,
            },
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("hugegraph/rag:1.9.2", result.stdout.splitlines())

    def test_release_script_rejects_mismatching_version_before_packaging(self):
        self.run_command("sync")
        self.copy_scripts("apache-release.sh")
        result = subprocess.run(
            ["bash", str(self.root / "scripts/apache-release.sh"), "99.99.99"],
            env={**os.environ, "PYTHON_FOR_RELEASE": sys.executable},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Release version must match root", result.stderr)
        self.assertFalse((self.root / "scripts/dist").exists())


if __name__ == "__main__":
    unittest.main()
