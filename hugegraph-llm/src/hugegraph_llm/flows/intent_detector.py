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

import threading
import re
import json
from typing import Any

from hugegraph_llm.config import llm_settings
from hugegraph_llm.flows import FlowName
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import get_chat_llm
from hugegraph_llm.flows.rag_flow_raw import RAGRAW_FLOW_DESC, RAGRAW_FLOW_DETAIL
from hugegraph_llm.flows.rag_flow_vector_only import RAGVECTORONLY_FLOW_DESC, RAGVECTORONLY_FLOW_DETAIL
from hugegraph_llm.flows.rag_flow_graph_only import RAGGRAPHONLY_FLOW_DESC, RAGGRAPHONLY_FLOW_DETAIL
from hugegraph_llm.flows.rag_flow_graph_vector import RAGGRAPHVECTOR_FLOW_DESC, RAGGRAPHVECTOR_FLOW_DETAIL

INTENT_DETECTOR_PROMPT = """
# ROLE
You are an expert AI assistant that functions as a flow router. Your primary responsibility is to analyze a user's query and select the most appropriate flow from a provided list to handle the request.

# INSTRUCTIONS
1. Carefully examine the user's query to understand their underlying intent.
2. Review the list of `AVAILABLE_FLOWS`. For each flow, pay close attention to its `desc` (description).
3. Select the single best flow based on query characteristics:
   - **Graph-only queries**: Use when the query focuses on relationships, connections, paths, network analysis, or graph traversal (e.g., "How are A and B connected?", "What's the shortest path between X and Y?", "Show me the network of relationships around Z")
   - **Vector-only queries**: Use when the query seeks factual information, definitions, descriptions, or content similarity (e.g., "What kind of person is X?", "Tell me about Y", "Describe the characteristics of Z")
   - **Hybrid queries**: Use when the query combines both relationship exploration AND factual retrieval, or when context from both graph structure and content semantics would enhance the answer
4. If no flow is suitable for the query, you MUST choose "none".
5. Your final output MUST be a single flow name string. Do not add any explanation or conversational text.

# AVAILABLE_FLOWS
Here is the list of flows you can choose from:
{{flow_list}}

# EXAMPLES
---
**Example 1**
**User Query:** "How are Tesla and Elon Musk connected?"
**Your Output:**
rag_graph_only
---
**Example 2**
**User Query:** "What kind of person is Elon Musk?"
**Your Output:**
rag_vector_only
---
**Example 3**
**User Query:** "Tell me about Elon Musk and his relationships with other companies."
**Your Output:**
rag_graph_vector
---
**Example 4**
**User Query:** "What's the weather like in London today?"
**Your Output:**
none
---

# TASK
Now, based on the flows, instructions, and examples above, process the following user query.

**User Query:** "{{user_query}}"

**Your Output:**
"""

PARAMETER_EXTRACTOR_PROMPT = """
# ROLE
You are an expert parameter extractor for flow execution. Your task is to analyze a user's query and extract the required parameters for a specific flow based on the flow's parameter specifications.

# INSTRUCTIONS
1. Carefully analyze the user's query to understand the intent and requirements.
2. Review the flow's parameter specifications, paying attention to parameter types, descriptions, and extraction rules.
3. Extract or infer the appropriate values for each required parameter based on the query content.
4. Follow the specific rules and conditions described for each parameter.
5. Your output MUST be a valid JSON object containing all required parameters with their extracted values.

# EXAMPLES
---
**Example 1**
**Flow Details:**
{
  "required_params": [
    {"name": "query", "type": "str", "desc": "User question"},
    {"name": "gremlin_tmpl_num", "type": "int", "desc": "Number of Gremlin templates to use. Set to 3 if the query contains clear graph query semantics that can be translated to Gremlin (such as finding relationships, paths, nodes, or graph traversal patterns). Set to -1 if the query semantics are ambiguous or cannot be clearly mapped to graph operations"}
  ]
}

**User Query:** "How are Tesla and SpaceX related to each other?"
**Your JSON Output:**
{
  "query": "How are Tesla and SpaceX related to each other?",
  "gremlin_tmpl_num": 3
}
---
**Example 2**
**Flow Details:**
{
  "required_params": [
    {"name": "query", "type": "str", "desc": "User question"},
    {"name": "gremlin_tmpl_num", "type": "int", "desc": "Number of Gremlin templates to use. Set to 3 if the query contains clear graph query semantics that can be translated to Gremlin (such as finding relationships, paths, nodes, or graph traversal patterns). Set to -1 if the query semantics are ambiguous or cannot be clearly mapped to graph operations"}
  ]
}

**User Query:** "Tell me about Elon Musk's background and his companies"
**Your JSON Output:**
{
  "query": "Tell me about Elon Musk's background and his companies",
  "gremlin_tmpl_num": -1
}
---

# TASK
**Flow Details:**
{{flow_detail}}

**User Query:** "{{user_query}}"

**Your JSON Output:**
"""


class IntentDetector:
    llm_client: BaseLLM
    flow_message: dict[str, Any]

    def __init__(self):
        self.llm_client = get_chat_llm(llm_settings)
        # add logic to init flow message include flow function and flow input
        self.flow_message = {}
        self.flow_message[FlowName.RAG_RAW] = {
            "desc": RAGRAW_FLOW_DESC,
            "detail": RAGRAW_FLOW_DETAIL,
        }
        self.flow_message[FlowName.RAG_VECTOR_ONLY] = {
            "desc": RAGVECTORONLY_FLOW_DESC,
            "detail": RAGVECTORONLY_FLOW_DETAIL,
        }
        self.flow_message[FlowName.RAG_GRAPH_ONLY] = {
            "desc": RAGGRAPHONLY_FLOW_DESC,
            "detail": RAGGRAPHONLY_FLOW_DETAIL,
        }
        self.flow_message[FlowName.RAG_GRAPH_VECTOR] = {
            "desc": RAGGRAPHVECTOR_FLOW_DESC,
            "detail": RAGGRAPHVECTOR_FLOW_DETAIL,
        }
        return

    async def detect(self, query: str, flow_list: list[str]):
        # Compose the prompt for the LLM by filling in the user query and tool descriptions
        result = {}
        tool_descs = []
        for flow in flow_list:
            if flow in self.flow_message:
                tool_descs.append(self.flow_message[flow]["desc"])
        tools_str = "\n\n".join(tool_descs)
        prompt = INTENT_DETECTOR_PROMPT.replace("{{tool_list}}", tools_str)
        prompt = prompt.replace("{{user_query}}", query)
        tool_result = await self.llm_client.agenerate(prompt=prompt)
        tool_result = tool_result.strip()
        # expected tool_result belong to [4 kinds of Flow]
        detail = None if self.flow_message[tool_result] is None else self.flow_message[tool_result]["detail"]
        if detail is None:
          raise ValueError("LLM返回的flow类型不在支持的RAGFlow范围内！")

        detail_prompt = PARAMETER_EXTRACTOR_PROMPT.replace("{{flow_detail}}", detail)
        detail_prompt = detail_prompt.replace("{{user_query}}", query)

        parameter_res = await self.llm_client.agenerate(prompt=detail_prompt)
        parameter_res = re.sub(
            r"```(?:json)?\n?(.+?)\n?```", r"\1", parameter_res, flags=re.DOTALL
        )
        parameter_res = parameter_res.strip()
        parameter_res = json.loads(parameter_res)
        result["tool_name"] = tool_result
        result["parameters"] = parameter_res
        flow_flags = {
            FlowName.RAG_RAW: {
                "vector_search": False,
                "graph_search": False,
                "raw_answer": True,
                "vector_only_answer": False,
                "graph_only_answer": False,
                "graph_vector_answer": False,
            },
            FlowName.RAG_GRAPH_ONLY: {
                "vector_search": False,
                "graph_search": True,
                "raw_answer": False,
                "vector_only_answer": False,
                "graph_only_answer": True,
                "graph_vector_answer": False,
            },
            FlowName.RAG_VECTOR_ONLY: {
                "vector_search": True,
                "graph_search": False,
                "raw_answer": False,
                "vector_only_answer": True,
                "graph_only_answer": False,
                "graph_vector_answer": False,
            },
            FlowName.RAG_GRAPH_VECTOR: {
                "vector_search": True,
                "graph_search": True,
                "raw_answer": False,
                "vector_only_answer": False,
                "graph_only_answer": False,
                "graph_vector_answer": True,
            },
        }

        if tool_result in flow_flags:
            result["parameters"].update(flow_flags[tool_result])

        return result

class IntentDetectorSingleton:
    _instance = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = IntentDetector()
        return cls._instance
