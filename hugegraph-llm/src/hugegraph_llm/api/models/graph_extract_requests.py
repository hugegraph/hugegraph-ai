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
from copy import deepcopy
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hugegraph_llm.config import llm_settings
from hugegraph_llm.operators.common_op.check_schema import CheckSchema

SchemaInput = Union[str, Dict[str, Any]]
ContentInput = Union[str, List[str]]


def _validate_schema_value(schema: SchemaInput) -> SchemaInput:
    if isinstance(schema, dict):
        if not schema:
            raise ValueError("schema must not be an empty object")
        CheckSchema(deepcopy(schema)).run()
        return schema

    schema_text = str(schema).strip()
    if not schema_text:
        raise ValueError("schema must not be empty")
    if schema_text.startswith("{"):
        try:
            parsed_schema = json.loads(schema_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"schema must be valid JSON: {exc.msg}") from exc
        if not isinstance(parsed_schema, dict) or not parsed_schema:
            raise ValueError("schema JSON must be a non-empty object")
        CheckSchema(deepcopy(parsed_schema)).run()
    return schema_text


class GraphExtractOptions(BaseModel):
    include_meta: bool = Field(default=False, description="Whether to include response metadata.")
    include_warnings: bool = Field(default=True, description="Whether to include extraction warnings.")


class GraphImportOptions(BaseModel):
    update_vid_embeddings: bool = Field(default=False, description="Whether to rebuild vid embeddings after import.")


class GraphExtractClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: Optional[str] = Field(default=None, description="HugeGraph graph name.")
    user: Optional[str] = Field(default=None, description="HugeGraph user.")
    pwd: Optional[str] = Field(default=None, description="HugeGraph password.")
    gs: Optional[str] = Field(default=None, description="HugeGraph graphspace.")

    @field_validator("graph", "user", "pwd", "gs", mode="before")
    @classmethod
    def blank_strings_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class GraphExtractRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content_type: Literal["text", "chunks"] = Field(
        default="text", description="Whether content is raw text or chunks."
    )
    content: Optional[ContentInput] = Field(default=None, description="Raw document text or pre-split chunks.")
    texts: Optional[ContentInput] = Field(default=None, description="Deprecated alias for content_type=text content.")
    schema_data: SchemaInput = Field(..., alias="schema", description="Graph schema JSON object/string, or graph name.")
    example_prompt: Optional[str] = Field(default=None, description="Extraction prompt header or examples.")
    extract_type: Literal["property_graph"] = Field(default="property_graph")
    language: Literal["zh", "en"] = Field(default="zh")
    split_type: Literal["document", "paragraph", "sentence"] = Field(default="document")
    max_parallel_chunks: Optional[int] = Field(default=None, description="Maximum chunk-level LLM calls per request.")
    include_meta: bool = Field(default=False, description="Whether to include response metadata.")
    include_warnings: bool = Field(default=True, description="Whether to include extraction warnings.")
    client_config: Optional[GraphExtractClientConfig] = Field(default=None)

    @staticmethod
    def _normalize_text_content(value: ContentInput) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("content must be a non-empty string when content_type is text")
        return value.strip()

    @staticmethod
    def _normalize_legacy_texts(value: ContentInput) -> str:
        if isinstance(value, str):
            return GraphExtractRequest._normalize_text_content(value)
        items = [text for text in value if isinstance(text, str) and text.strip()]
        if len(items) != 1:
            raise ValueError("texts alias must contain exactly one non-empty string")
        return items[0].strip()

    @staticmethod
    def _normalize_chunks(value: ContentInput) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("content must be a non-empty list of strings when content_type is chunks")
        items = []
        for chunk in value:
            if not isinstance(chunk, str) or not chunk.strip():
                raise ValueError("chunks content must contain only non-empty strings")
            items.append(chunk.strip())
        if not items:
            raise ValueError("chunks content must contain at least one non-empty string")
        return items

    @staticmethod
    def _validate_parallel_chunks(value: Optional[int]) -> int:
        requested = llm_settings.graph_extract_max_parallel_chunks if value is None else value
        limit = llm_settings.graph_extract_max_parallel_chunks_limit
        if requested < 1:
            raise ValueError("max_parallel_chunks must be greater than or equal to 1")
        if requested > limit:
            raise ValueError(f"max_parallel_chunks must be less than or equal to {limit}")
        return requested

    @property
    def schema(self) -> SchemaInput:
        return self.schema_data

    @property
    def graph_schema(self) -> SchemaInput:
        return self.schema_data

    @property
    def options(self) -> GraphExtractOptions:
        return GraphExtractOptions(include_meta=self.include_meta, include_warnings=self.include_warnings)

    @field_validator("schema_data")
    @classmethod
    def validate_schema(cls, schema: SchemaInput) -> SchemaInput:
        return _validate_schema_value(schema)

    @model_validator(mode="after")
    def validate_schema_and_client_config(self):
        if self.content is not None and self.texts is not None:
            raise ValueError("content and deprecated texts alias cannot be provided together")

        if self.content is None:
            if self.texts is None:
                raise ValueError("content is required")
            if self.content_type != "text":
                raise ValueError("texts alias can only be used with content_type='text'")
            text = self._normalize_legacy_texts(self.texts)
            self.content = text
            self.texts = [text]
        elif self.content_type == "text":
            text = self._normalize_text_content(self.content)
            self.content = text
            self.texts = [text]
        else:
            if self.split_type != "document":
                raise ValueError("split_type must be 'document' when content_type is chunks")
            chunks = self._normalize_chunks(self.content)
            self.content = chunks
            self.texts = chunks

        self.max_parallel_chunks = self._validate_parallel_chunks(self.max_parallel_chunks)

        return self._validate_schema_client_config()

    def _validate_schema_client_config(self):
        schema = self.schema_data
        is_named_schema = isinstance(schema, str) and not schema.strip().startswith("{")
        if not is_named_schema:
            if self.client_config is not None:
                raise ValueError(
                    "client_config is not allowed when 'schema' is inline JSON; graph extraction "
                    "from an inline schema does not connect to HugeGraph."
                )
            return self
        if self.client_config is None:
            raise ValueError(
                "client_config is required when 'schema' refers to an existing graph name; "
                "provide inline schema JSON instead to extract without a HugeGraph connection."
            )
        if self.client_config.graph != schema:
            raise ValueError(
                "When 'schema' is a graph name, client_config.graph must match it "
                f"(got schema='{schema}', client_config.graph='{self.client_config.graph}')."
            )
        return self


class GraphImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_data: SchemaInput = Field(..., alias="schema", description="Graph schema JSON object/string, or graph name.")
    data: Dict[str, Any] = Field(..., description="Property graph data with vertices and edges.")
    write_to_graph: bool = Field(default=False, description="Required confirmation for graph writes.")
    client_config: Optional[GraphExtractClientConfig] = Field(default=None)
    options: GraphImportOptions = Field(default_factory=GraphImportOptions)

    @property
    def schema(self) -> SchemaInput:
        return self.schema_data

    @field_validator("schema_data")
    @classmethod
    def validate_schema(cls, schema: SchemaInput) -> SchemaInput:
        return _validate_schema_value(schema)

    @field_validator("data")
    @classmethod
    def validate_data(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        vertices = data.get("vertices") or []
        edges = data.get("edges") or []
        triples = data.get("triples") or []
        if triples and not vertices and not edges:
            raise ValueError("triples-only import is not supported; submit property graph vertices or edges")
        if not vertices and not edges and not triples:
            raise ValueError("data must contain at least one vertex, edge, or triple")
        return data


class GraphExtractAndImportRequest(GraphExtractRequest):
    write_to_graph: bool = Field(default=False, description="Required confirmation for graph writes.")
    import_options: GraphImportOptions = Field(default_factory=GraphImportOptions)

    def _validate_schema_client_config(self):
        schema = self.schema_data
        is_named_schema = isinstance(schema, str) and not schema.strip().startswith("{")
        if not is_named_schema:
            return self
        if self.client_config is None:
            raise ValueError(
                "client_config is required when 'schema' refers to an existing graph name; "
                "provide inline schema JSON instead to extract without a HugeGraph connection."
            )
        if self.client_config.graph != schema:
            raise ValueError(
                "When 'schema' is a graph name, client_config.graph must match it "
                f"(got schema='{schema}', client_config.graph='{self.client_config.graph}')."
            )
        return self
