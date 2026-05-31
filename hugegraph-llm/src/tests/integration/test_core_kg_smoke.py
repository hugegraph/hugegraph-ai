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

import json
from pathlib import Path

import pytest
from pyhugegraph.client import PyHugeClient

pytestmark = [pytest.mark.smoke, pytest.mark.integration, pytest.mark.hugegraph]

QUALITY_COMMIT_SCHEMA = {
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "lang", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "date", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
    "vertexlabels": [
        {
            "name": "quality_person",
            "properties": ["name", "age"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        },
        {
            "name": "quality_software",
            "properties": ["name", "lang"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        },
    ],
    "edgelabels": [
        {
            "name": "quality_created",
            "source_label": "quality_person",
            "target_label": "quality_software",
            "properties": ["date"],
        }
    ],
}


def _make_client(service):
    return PyHugeClient(
        url=service.url,
        graph=service.graph,
        user=service.user,
        pwd=service.password,
        graphspace=service.graphspace,
    )


@pytest.fixture()
def configured_hugegraph(hugegraph_service):
    from hugegraph_llm.config import huge_settings

    original = {
        "graph_url": huge_settings.graph_url,
        "graph_name": huge_settings.graph_name,
        "graph_user": huge_settings.graph_user,
        "graph_pwd": huge_settings.graph_pwd,
        "graph_space": huge_settings.graph_space,
    }
    huge_settings.graph_url = hugegraph_service.url
    huge_settings.graph_name = hugegraph_service.graph
    huge_settings.graph_user = hugegraph_service.user
    huge_settings.graph_pwd = hugegraph_service.password
    huge_settings.graph_space = hugegraph_service.graphspace

    client = _make_client(hugegraph_service)
    client.graphs().clear_graph_all_data()
    try:
        yield hugegraph_service
    finally:
        try:
            client.graphs().clear_graph_all_data()
        finally:
            for key, value in original.items():
                setattr(huge_settings, key, value)


def test_kg_construction_smoke_uses_production_code(configured_hugegraph):
    from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
    from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData

    fixture_file = Path(__file__).resolve().parents[1] / "data" / "quality_program" / "kg_graph_output.json"
    fixture = json.loads(fixture_file.read_text(encoding="utf-8"))
    assert fixture["vertices"]
    assert fixture["edges"]

    data = {
        "schema": QUALITY_COMMIT_SCHEMA,
        "vertices": fixture["vertices"],
        "edges": fixture["edges"],
    }
    Commit2Graph().run(data)

    client = _make_client(configured_hugegraph)
    summary = FetchGraphData(client).run({})
    assert summary["vertex_num"] >= len(fixture["vertices"])
    assert summary["edge_num"] >= len(fixture["edges"])
