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

"""W3C trace-context reference carried through evaluation records."""

from pydantic import Field, field_validator

from hugegraph_llm_eval.contracts.base import StrictModel


class SpanContextRef(StrictModel):
    trace_id: str
    span_id: str
    trace_flags: int = Field(default=0, ge=0, le=255)
    trace_state: str = Field(default="", max_length=512)
    is_remote: bool = False

    @field_validator("trace_id")
    @classmethod
    def _validate_trace_id(cls, value: str) -> str:
        if len(value) != 32 or value == "0" * 32 or any(char not in "0123456789abcdef" for char in value):
            msg = "trace_id must be 32 lowercase hex characters and non-zero"
            raise ValueError(msg)
        return value

    @field_validator("span_id")
    @classmethod
    def _validate_span_id(cls, value: str) -> str:
        if len(value) != 16 or value == "0" * 16 or any(char not in "0123456789abcdef" for char in value):
            msg = "span_id must be 16 lowercase hex characters and non-zero"
            raise ValueError(msg)
        return value
