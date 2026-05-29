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

import importlib.util
import textwrap
from pathlib import Path


def _load_lint_module():
    repo_root = Path(__file__).resolve().parents[3]
    spec_path = repo_root / "scripts" / "lint_async_no_requests.py"
    spec = importlib.util.spec_from_file_location("lint_async_no_requests", spec_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_file_flags_requests_call_in_async(tmp_path):
    module = _load_lint_module()
    bad = tmp_path / "bad.py"
    bad.write_text(
        textwrap.dedent(
            """
            import requests
            async def fetch():
                return requests.get('http://example.com').json()
            """
        ).strip(),
        encoding="utf-8",
    )
    # bypass exempt-suffix check by patching REPO_ROOT
    module.REPO_ROOT = tmp_path
    violations = module.check_file(bad)
    assert len(violations) == 1
    assert "requests.get" in violations[0][2]


def test_check_file_passes_clean_async(tmp_path):
    module = _load_lint_module()
    good = tmp_path / "good.py"
    good.write_text(
        textwrap.dedent(
            """
            import httpx
            async def fetch(client):
                resp = await client.get('http://example.com')
                return resp.json()
            """
        ).strip(),
        encoding="utf-8",
    )
    module.REPO_ROOT = tmp_path
    violations = module.check_file(good)
    assert violations == []


def test_check_file_ignores_sync_functions(tmp_path):
    module = _load_lint_module()
    sync = tmp_path / "sync_only.py"
    sync.write_text(
        textwrap.dedent(
            """
            import requests
            def sync_fetch():
                return requests.get('http://x').json()
            """
        ).strip(),
        encoding="utf-8",
    )
    module.REPO_ROOT = tmp_path
    violations = module.check_file(sync)
    assert violations == []
