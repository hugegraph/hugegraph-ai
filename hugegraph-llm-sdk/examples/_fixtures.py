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

"""Small fixed responses for offline examples; these are not quality benchmarks."""

TEXT = "Alice works for Acme."

SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["name"],
            "properties": ["name"],
            "nullable_keys": [],
        },
        {
            "id": 2,
            "name": "company",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["name"],
            "properties": ["name"],
            "nullable_keys": [],
        },
    ],
    "edgelabels": [{"name": "works_for", "source_label": "person", "target_label": "company", "properties": []}],
    "propertykeys": [{"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"}],
}

GRAPH = {
    "vertices": [
        {"id": "1:Alice", "label": "person", "properties": {"name": "Alice"}},
        {"id": "2:Acme", "label": "company", "properties": {"name": "Acme"}},
    ],
    "edges": [
        {
            "label": "works_for",
            "outV": "1:Alice",
            "inV": "2:Acme",
            "outVLabel": "person",
            "inVLabel": "company",
            "properties": {},
        }
    ],
}

PASS_REVIEW = {"decision": "pass", "issues": []}
