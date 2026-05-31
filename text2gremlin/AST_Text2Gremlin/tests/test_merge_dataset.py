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

# ruff: noqa: E402

import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from llm_augment.merge_dataset import compute_crud_stats, guess_operation


def test_guess_operation_classifies_common_gremlin_operations():
    assert guess_operation("g.addV('person').property('name', 'marko')") == "create"
    assert guess_operation("g.V().addE('knows').to(__.V().has('id', 1))") == "create"
    assert guess_operation("g.V().has('id', 1).property('name', 'josh')") == "update"
    assert guess_operation("g.V().has('id', 1).drop()") == "delete"
    assert guess_operation("g.V().hasLabel('person')") == "read"


def test_compute_crud_stats_fills_unknown_operations_in_place():
    pairs = [
        {"operation": "unknown", "gremlin": "g.V().hasLabel('person')"},
        {"operation": "", "gremlin": "g.V().has('id', 1).property('name', 'josh')"},
        {"operation": "delete", "gremlin": "g.V().has('id', 1).drop()"},
    ]

    stats = compute_crud_stats(pairs)

    assert stats == {"read": 1, "update": 1, "delete": 1}
    assert [pair["operation"] for pair in pairs] == ["read", "update", "delete"]


def test_main_exits_nonzero_when_required_inputs_are_missing(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "llm_augment.merge_dataset", "--output-dir", str(tmp_path)],
        cwd=PROJECT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "未找到 llm_translated" in result.stderr
