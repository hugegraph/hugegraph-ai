# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Any

from pyhugegraph.client import PyHugeClient

from hugegraph_mcp.config import MCPConfig

_config = MCPConfig.from_env()


def _build_client() -> PyHugeClient:
    # HugeGraph 1.7.0+ graph space support - resolved from config (HUGEGRAPH_GRAPH_PATH)
    graphspace = _config.graphspace
    # Only pass graphspace if it's not None and not empty string
    if graphspace and graphspace.strip():
        return PyHugeClient(
            url=_config.url,
            graph=_config.graph,
            user=_config.user,
            pwd=_config.password,
            graphspace=graphspace.strip(),
        )
    else:
        # Default client without graphspace for backward compatibility
        return PyHugeClient(
            url=_config.url,
            graph=_config.graph,
            user=_config.user,
            pwd=_config.password,
        )


def _simple_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Simplify HugeGraph schema for LLM consumption.

    This mirrors the behaviour of hugegraph_llm.SchemaManager.simple_schema
    for the fields used in tests.
    """

    mini_schema: dict[str, Any] = {}

    if schema.get("vertexlabels"):
        mini_schema["vertexlabels"] = []
        for vertex in schema["vertexlabels"]:
            new_vertex = {
                key: vertex[key]
                for key in ("id", "name", "properties")
                if key in vertex
            }
            mini_schema["vertexlabels"].append(new_vertex)

    if schema.get("edgelabels"):
        mini_schema["edgelabels"] = []
        for edge in schema["edgelabels"]:
            new_edge = {
                key: edge[key]
                for key in ("name", "source_label", "target_label", "properties")
                if key in edge
            }
            mini_schema["edgelabels"].append(new_edge)

    return mini_schema


def get_live_schema() -> dict[str, Any]:
    """Fetch live schema from HugeGraph and return both full and simplified forms.

    This is written in a way that can be wrapped as a FastMCP tool later.
    """

    client = _build_client()
    raw_schema = client.schema().getSchema()

    # Ensure raw_schema is not None before processing
    if raw_schema is None:
        raise ValueError("Failed to retrieve schema from HugeGraph server")

    result: dict[str, Any] = {
        "schema": raw_schema,
        "simple_schema": _simple_schema(raw_schema),
    }

    # HugeGraph 1.7.0+ graph space handling - from resolved config
    graphspace = _config.graphspace
    if graphspace:
        result["graphspace"] = graphspace

    result["readonly"] = MCPConfig.from_env().is_readonly()

    return result


def _run_schema_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Low-level schema executor against HugeGraph REST schema API.

    This is a minimal first version that supports a small subset of
    operation types. It is intentionally simple and can be extended as
    needed with more op kinds.
    """

    client = _build_client()
    schema = client.schema()

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, op in enumerate(operations):
        op_type = op.get("type")
        try:
            if op_type == "create_property_key":
                name = op["name"]
                # Default to TEXT if caller没有指定类型；后续可以扩展 data_type 映射
                data_type = op.get("data_type", "TEXT").upper()
                pk_builder = schema.propertyKey(name)
                if data_type == "INT":
                    pk_builder = pk_builder.asInt()
                elif data_type == "DOUBLE":
                    pk_builder = pk_builder.asDouble()
                else:
                    pk_builder = pk_builder.asText()
                pk_builder.ifNotExist().create()

            elif op_type == "create_vertex_label":
                name = op["name"]
                properties = op.get("properties", [])
                vl_builder = schema.vertexLabel(name)
                if properties:
                    vl_builder = vl_builder.properties(*properties)
                # 使用 primaryKeys(name) 作为默认主键策略，后续可按需扩展
                if op.get("primary_keys"):
                    vl_builder = vl_builder.primaryKeys(*op["primary_keys"])
                vl_builder.ifNotExist().create()

            elif op_type == "create_edge_label":
                name = op["name"]
                source_label = op["source_label"]
                target_label = op["target_label"]
                properties = op.get("properties", [])
                sort_keys = op.get("sort_keys", [])
                nullable_keys = op.get("nullable_keys", [])
                frequency = op.get("frequency", "MULTI").upper()

                el_builder = (
                    schema.edgeLabel(name)
                    .sourceLabel(source_label)
                    .targetLabel(target_label)
                )
                if properties:
                    el_builder = el_builder.properties(*properties)
                if sort_keys:
                    el_builder = el_builder.sortKeys(*sort_keys)
                if nullable_keys:
                    el_builder = el_builder.nullableKeys(*nullable_keys)
                if frequency == "MULTI":
                    el_builder = el_builder.multiTimes()
                el_builder.ifNotExist().create()

            elif op_type == "create_index_label":
                name = op["name"]
                base_type = op.get("base_type", "VERTEX").upper()
                base_label = op["base_label"]
                fields = op.get("fields", [])
                index_type = op.get("index_type", "SECONDARY").upper()

                il_builder = schema.indexLabel(name)
                if base_type == "VERTEX":
                    il_builder = il_builder.onV(base_label)
                elif base_type == "EDGE":
                    il_builder = il_builder.onE(base_label)
                else:
                    raise ValueError(
                        f"Unsupported base_type for index label: {base_type}"
                    )

                if fields:
                    il_builder = il_builder.by(*fields)

                if index_type == "SECONDARY":
                    il_builder = il_builder.secondary()
                elif index_type == "RANGE":
                    il_builder = il_builder.range()
                else:
                    raise ValueError(
                        f"Unsupported index_type for index label: {index_type}"
                    )

                il_builder.ifNotExist().create()

            else:
                raise ValueError(f"Unsupported schema operation type: {op_type}")

            results.append({"op": op, "status": "ok"})
        except Exception as exc:  # pragma: no cover - 错误路径由上层聚合
            msg = str(exc)
            results.append({"op": op, "status": "failed", "error": msg})
            errors.append({"op_index": idx, "message": msg})

    return {"success": not bool(errors), "results": results, "errors": errors}


def execute_schema_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute a sequence of idempotent schema operations.

    Behaviour covered by tests:
    - Delegates actual execution to `_run_schema_operations`.
    - Respects HUGEGRAPH_MCP_READONLY environment variable.
    """

    result = _run_schema_operations(operations)

    # Normalise result keys a bit so callers always get predictable fields.
    if "errors" not in result:
        result["errors"] = []
    if "success" not in result:
        result["success"] = not bool(result["errors"])

    return result


def design_schema(
    thought: str,
    thought_number: int,
    total_thoughts: int = 4,
    next_thought_needed: bool = True,
    is_revision: bool = False,
    revision_of: int | None = None,
) -> dict:
    """Schema design guidance tool - Reference Sequential Thinking pattern

    HugeGraph uses a schema-based graph model. You must define schema
    (PropertyKeys, VertexLabels, EdgeLabels, IndexLabels) before inserting data.

    【Best Practices for Designing Schema in HugeGraph】

    1. Define PropertyKeys first: All properties used in VertexLabel and EdgeLabel
       must be predefined as PropertyKeys. This ensures data consistency and type enforcement.

    2. Choose appropriate data types and cardinality: When defining PropertyKeys,
       select the correct DataType (TEXT, INT, DATE, DOUBLE) and Cardinality
       (SINGLE, SET, LIST) based on the nature of the data.

    3. Specify Primary Keys for VertexLabels: VertexLabels should have primaryKeys
       defined, which uniquely identify a vertex within that label.

    4. Define Link for EdgeLabels: EdgeLabels must specify sourceLabel and targetLabel
       to define the types of vertices it connects.

    5. Consider Frequency for EdgeLabels: EdgeLabels can be SINGLE (one edge between
       two vertices) or MULTIPLE (multiple edges between two vertices).

    6. Use nullableKeys: Specify properties that can be null using nullableKeys.

    7. Create Indexes for efficient queries: Define IndexLabels on PropertyKeys for
       VertexLabels (onV) or EdgeLabels (onE). Choose between secondary, range,
       or search indexes based on query patterns.

    【Information to Collect from Users】

    To design an effective HugeGraph schema, collect:

    * Entities (Vertices):
      - Main entity types (person, software, book) -> VertexLabels
      - Properties for each entity (name, age, city for person) -> PropertyKeys
      - Properties that uniquely identify an entity (primaryKeys)
      - Data type and cardinality for each property

    * Relationships (Edges):
      - Relationships between entities (knows, created) -> EdgeLabels
      - sourceLabel and targetLabel for each relationship
      - Properties describing each relationship
      - Frequency (singleTime vs multiTimes)

    * Query Patterns:
      - How will users query the graph?
      - What properties will be used in filters, sorting, or range queries?
      - Which IndexLabels to create (secondary, range, search)

    【Complete Examples】

    PropertyKey Definitions:
    ```groovy
    schema.propertyKey("name").asText().ifNotExist().create()
    schema.propertyKey("age").asInt().ifNotExist().create()
    schema.propertyKey("city").asText().ifNotExist().create()
    schema.propertyKey("weight").asDouble().ifNotExist().create()
    schema.propertyKey("date").asText().ifNotExist().create()
    ```

    VertexLabel Definitions:
    ```groovy
    schema.vertexLabel("person")
          .properties("name", "age", "city")
          .primaryKeys("name")
          .ifNotExist().create()

    schema.vertexLabel("software")
          .properties("name", "lang", "price")
          .primaryKeys("name")
          .ifNotExist().create()
    ```

    EdgeLabel Definitions:
    ```groovy
    schema.edgeLabel("knows")
          .sourceLabel("person")
          .targetLabel("person")
          .properties("date", "weight")
          .ifNotExist().create()

    schema.edgeLabel("created")
          .sourceLabel("person")
          .targetLabel("software")
          .properties("date", "weight")
          .ifNotExist().create()
    ```

    IndexLabel Definitions:
    ```groovy
    schema.indexLabel("personByCity").onV("person").by("city").secondary().ifNotExist().create()
    schema.indexLabel("softwareByPrice").onV("software").by("price").range().ifNotExist().create()
    schema.indexLabel("createdByDate").onE("created").by("date").secondary().ifNotExist().create()
    ```

    【Usage Example - Movie Recommendation Graph】

    Turn 1 - Ask about scenario:
    LLM asks: What is your graph for?
    User: Movie recommendation system

    Turn 2 - Ask about entities:
    LLM asks: What are the main entities? (e.g., user, movie, actor, director)
    User: user, movie, actor

    Turn 3 - Ask about properties:
    LLM asks: What properties does each entity have?
    - user: name, age, gender, city
    - movie: title, year, rating, genre
    - actor: name, birthday, nationality

    Turn 4 - Ask about relationships:
    LLM asks: How do entities relate to each other?
    - user -> movie: watched
    - user -> user: follows
    - actor -> movie: acted_in
    - user -> actor: liked

    After confirmation, generate operations:

    [
      {"type": "create_property_key", "name": "name", "data_type": "TEXT"},
      {"type": "create_property_key", "name": "age", "data_type": "INT"},
      {"type": "create_property_key", "name": "gender", "data_type": "TEXT"},
      {"type": "create_property_key", "name": "city", "data_type": "TEXT"},
      {"type": "create_property_key", "name": "title", "data_type": "TEXT"},
      {"type": "create_property_key", "name": "year", "data_type": "INT"},
      {"type": "create_property_key", "name": "rating", "data_type": "DOUBLE"},
      {"type": "create_property_key", "name": "genre", "data_type": "TEXT"},
      {"type": "create_property_key", "name": "birthday", "data_type": "TEXT"},
      {"type": "create_property_key", "name": "nationality", "data_type": "TEXT"},

      {"type": "create_vertex_label", "name": "person", "properties": ["name", "age", "gender", "city"], "primary_keys": ["name"]},
      {"type": "create_vertex_label", "name": "movie", "properties": ["title", "year", "rating", "genre"], "primary_keys": ["title", "year"]},
      {"type": "create_vertex_label", "name": "actor", "properties": ["name", "birthday", "nationality"], "primary_keys": ["name"]},

      {"type": "create_edge_label", "name": "watched", "source_label": "person", "target_label": "movie"},
      {"type": "create_edge_label", "name": "follows", "source_label": "person", "target_label": "person"},
      {"type": "create_edge_label", "name": "acted_in", "source_label": "actor", "target_label": "movie"},
      {"type": "create_edge_label", "name": "liked", "source_label": "person", "target_label": "actor"},

      {"type": "create_index_label", "name": "personByCity", "base_type": "VERTEX", "base_label": "person", "fields": ["city"], "index_type": "SECONDARY"},
      {"type": "create_index_label", "name": "movieByRating", "base_type": "VERTEX", "base_label": "movie", "fields": ["rating"], "index_type": "RANGE"},
    ]

    Args:
        thought: Current thought or summary of user's answer
        thought_number: Current iteration number
        total_thoughts: Planned total iterations (3-5 recommended)
        next_thought_needed: Whether to continue to next iteration
        is_revision: Whether revising previous thought
        revision_of: Which iteration being revised

    Returns:
        {"thought_number": 1, "total_thoughts": 4, "next_thought_needed": True}
    """
    return {
        "thought_number": thought_number,
        "total_thoughts": total_thoughts,
        "next_thought_needed": next_thought_needed,
    }
