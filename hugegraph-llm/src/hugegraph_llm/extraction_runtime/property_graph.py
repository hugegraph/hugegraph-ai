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

"""Legacy application defaults around the independent property-graph runtime."""

from hugegraph_llm_sdk.extraction_runtime.property_graph import PropertyGraphBundle as CorePropertyGraphBundle
from hugegraph_llm_sdk.prompts import GraphPrompts

from hugegraph_llm.config import prompt, runtime_config_lock
from hugegraph_llm.models.llms.base import BaseLLM


def snapshot_graph_prompts() -> GraphPrompts:
    """Read the application's current prompts once before a chunk batch starts."""
    with runtime_config_lock:
        return GraphPrompts(
            extract=prompt.extract_graph_prompt,
            review=prompt.review_graph_prompt,
            repair=prompt.repair_graph_prompt,
        )


class PropertyGraphBundle(CorePropertyGraphBundle):
    """Preserve application prompt defaults while sharing core validation and review."""

    def __init__(
        self,
        *,
        llm: BaseLLM,
        schema: dict,
        example_prompt: str | None = None,
        prompts: GraphPrompts | None = None,
    ):
        super().__init__(
            llm=llm,
            schema=schema,
            example_prompt=example_prompt,
            prompts=snapshot_graph_prompts() if prompts is None else prompts,
        )
