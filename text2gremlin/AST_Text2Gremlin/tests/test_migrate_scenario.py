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

# ruff: noqa: E402,I001

import sys
import types
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

base_module = types.ModuleType("base")
generator_module = types.ModuleType("base.generator")
generator_module.check_gremlin_syntax = lambda query: (True, "Syntax OK")
sys.modules.setdefault("base", base_module)
sys.modules.setdefault("base.generator", generator_module)

from llm_augment.migrate_scenario import (
    GeneratedSample,
    build_migration_prompt,
    filter_generated_samples,
    get_migration_config,
    infer_operation_type,
)


SIMPLE_SCHEMA = {
    "vertices": [{"label": "user", "properties": ["name"]}],
    "edges": [],
}


def test_same_operation_prompt_is_default_and_uses_configured_sample_count():
    config = get_migration_config({})

    assert config["migration_mode"] == "same_operation"
    assert config["same_operation_sample_count"] == 3

    prompt = build_migration_prompt(
        "Find all users",
        "g.V().hasLabel('user')",
        SIMPLE_SCHEMA,
        migration_mode=config["migration_mode"],
        sample_count=config["same_operation_sample_count"],
    )

    assert "生成 3 条样本" in prompt
    assert "只生成与原始 Gremlin 同类型的 read 操作" in prompt
    assert "2 条 read类型语句" not in prompt
    assert "1 条 create类型语句" not in prompt


def test_same_operation_prompt_uses_operation_matching_examples():
    create_prompt = build_migration_prompt(
        "Create a movie",
        "g.addV('movie').property('title', 'Dune')",
        SIMPLE_SCHEMA,
        migration_mode="same_operation",
    )
    update_prompt = build_migration_prompt(
        "Update a movie title",
        "g.V().hasLabel('movie').property('title', 'Dune 2')",
        SIMPLE_SCHEMA,
        migration_mode="same_operation",
    )
    delete_prompt = build_migration_prompt(
        "Delete a movie",
        "g.V().hasLabel('movie').drop()",
        SIMPLE_SCHEMA,
        migration_mode="same_operation",
    )

    assert '"operation": "create"' in create_prompt
    assert '"query": "g.addV' in create_prompt
    assert '"operation": "update"' in update_prompt
    assert ".property(" in update_prompt
    assert '"operation": "delete"' in delete_prompt
    assert ".drop()" in delete_prompt


def test_migration_config_can_override_mode_and_sample_count():
    config = get_migration_config(
        {
            "migration": {
                "migration_mode": "mixed_operations",
                "same_operation_sample_count": 5,
            }
        }
    )

    assert config["migration_mode"] == "mixed_operations"
    assert config["same_operation_sample_count"] == 5


def test_mixed_operations_prompt_keeps_crud_distribution_guidance():
    prompt = build_migration_prompt(
        "Find all users",
        "g.V().hasLabel('user')",
        SIMPLE_SCHEMA,
        migration_mode="mixed_operations",
        sample_count=3,
    )

    assert "2 条 read类型语句" in prompt
    assert "1 条 create类型语句" in prompt
    assert "1 条 update类型" in prompt
    assert "1 条 delete类型语句" in prompt


def test_infer_operation_type_from_gremlin():
    assert infer_operation_type("g.addV('person').property('name', 'marko')") == "create"
    assert infer_operation_type("g.V().has('id', 1).property('name', 'josh')") == "update"
    assert infer_operation_type("g.V().has('id', 1).drop()") == "delete"
    assert infer_operation_type("g.V().hasLabel('person')") == "read"


def test_same_operation_filter_rejects_mismatched_operation_and_query_type():
    samples = [
        GeneratedSample(
            operation="read",
            language_style="zh_formal",
            query="g.V().hasLabel('person')",
            natural_language="查询所有人",
        ),
        GeneratedSample(
            operation="create",
            language_style="zh_formal",
            query="g.addV('person')",
            natural_language="创建一个人",
        ),
        GeneratedSample(
            operation="read",
            language_style="zh_formal",
            query="g.V().hasLabel('person').drop()",
            natural_language="删除人",
        ),
    ]

    filtered = filter_generated_samples(samples, "read", "same_operation")

    assert len(filtered) == 1
    assert filtered[0]["query"] == "g.V().hasLabel('person')"
