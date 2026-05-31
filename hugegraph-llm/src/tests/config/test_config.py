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


import unittest
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


class TestConfig(unittest.TestCase):
    def test_config(self):
        import nltk

        from hugegraph_llm.config import resource_path

        nltk.data.path.append(resource_path)
        nltk.data.find("corpora/stopwords")

    def test_prompt_yaml_path_is_project_root_independent(self):
        from hugegraph_llm.config.models import base_prompt_config

        expected = Path(__file__).resolve().parents[2] / "hugegraph_llm" / "resources" / "demo" / "config_prompt.yaml"
        self.assertEqual(Path(base_prompt_config.yaml_file_path), expected)

    def test_env_path_is_project_root_independent(self):
        from hugegraph_llm.config.models import base_config

        expected = Path(__file__).resolve().parents[3] / ".env"
        self.assertEqual(Path(base_config.env_path), expected)
