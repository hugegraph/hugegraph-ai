#!/usr/bin/env python3
#
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

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / ".github" / "fixtures" / "ai-review"
SCRIPT_PATH = ROOT / ".github" / "scripts" / "check-ai-review-quality.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_ai_review_quality", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


quality = _load_module()


class CheckAIReviewQualityTest(unittest.TestCase):
    def test_fixture_decisions(self):
        cases = [
            ("no-review", True, "missing_review"),
            ("short-review", True, "review_too_shallow"),
            ("good-review", False, "review_present"),
            ("max-retry-reached", False, "max_retries_reached"),
            ("stale-review", True, "missing_review"),
            ("non-reviewer", True, "missing_review"),
        ]

        for name, needs_retry, reason in cases:
            with self.subTest(name=name):
                result = quality.evaluate_review_quality(
                    comments=_read_fixture(f"{name}-comments.json"),
                    reviews=_read_fixture(f"{name}-reviews.json"),
                    min_chars=800,
                    max_retries=2,
                )
                self.assertIs(result["needs_retry"], needs_retry)
                self.assertEqual(result["reason"], reason)


def _read_fixture(name: str) -> list[dict]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
