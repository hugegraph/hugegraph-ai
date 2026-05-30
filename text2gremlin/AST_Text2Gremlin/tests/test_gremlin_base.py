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

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from base.GremlinBase import GremlinBase


class SchemaOnlyConfig:
    def __init__(self, schema_dict_path: str):
        self.schema_dict_path = schema_dict_path

    def get_schema_dict_path(self):
        return [self.schema_dict_path]

    def get_syn_dict_path(self):
        return None


def test_schema_and_syn_dictionaries_fall_back_independently(tmp_path):
    schema_dict = tmp_path / "schema_dict.txt"
    schema_dict.write_text("custom 自定义\n", encoding="utf-8")

    gremlin_base = GremlinBase(SchemaOnlyConfig(str(schema_dict)))

    assert gremlin_base.schema_dict["custom"] == ["自定义"]
    assert gremlin_base.schema_dict["1"] == ["一"]
