import threading

from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.llms.base import BaseLLM
from hugegraph_llm.models.llms.init_llm import get_chat_llm
from hugegraph_llm.flows.rag_flow_raw import RAGRAW_FLOW_PROMPT
from hugegraph_llm.flows.rag_flow_vector_only import RAGVECTORONLY_FLOW_PROMPT
from hugegraph_llm.flows.rag_flow_graph_only import RAGGRAPHONLY_FLOW_PROMPT
from hugegraph_llm.flows.rag_flow_graph_vector import RAGGRAPHVECTOR_FLOW_PROMPT

INTENT_DETECTOR_PROMPT = """
# ROLE
You are an expert AI assistant that functions as a tool router. Your primary responsibility is to analyze a user's query and select the most appropriate tool from a provided list to handle the request. You must also extract the necessary parameters for the selected tool from the query.

# INSTRUCTIONS
1.  Carefully examine the user's query to understand their underlying intent.
2.  Review the list of `AVAILABLE_TOOLS`. For each tool, pay close attention to its `desc` (description), `required_params`, and `optional_params`.
3.  Select the single best tool that can fulfill the user's request.
4.  If no tool is suitable for the query, you MUST choose "none".
5.  Extract the values for the tool's parameters from the user's query.
    - For required parameters, you must find a value in the query.
    - For optional parameters, extract them if they are mentioned.
    - For boolean parameters, infer `true` if the user's language suggests enabling a feature, otherwise omit it or use the default.
6.  Your final output MUST be a single JSON object containing two keys: "tool_name" and "parameters". Do not add any explanation or conversational text.

# AVAILABLE_TOOLS
Here is the list of tools you can choose from:
{{tool_list}}

# EXAMPLES
---
**Example 1**
**User Query:** "Tell me about knowledge graphs."
**Your JSON Output:**
{
  "tool_name": "rag_graph_vector",
  "parameters": {
    "query": "Tell me about knowledge graphs.",
    "graph_vector_answer": true
  }
}
---
**Example 2**
**User Query:** "I need to find info on Neo4j. Please use both graph and vector search, but I only want to see the graph-based answer. Also, prioritize nearest neighbors."
**Your JSON Output:**
{
  "tool_name": "rag_graph_vector",
  "parameters": {
    "query": "Find info on Neo4j",
    "graph_vector_answer": true,
    "graph_only_answer": true,
    "near_neighbor_first": true
  }
}
---
**Example 3**
**User Query:** "What's the weather like in London today?"
**Your JSON Output:**
{
  "tool_name": "none",
  "parameters": {}
}
---

# TASK
Now, based on the tools, instructions, and examples above, process the following user query.

**User Query:** "{{user_query}}"

**Your JSON Output:**
"""


class IntentDetector:
    llm_client: BaseLLM
    flow_message: dict[str, str]

    def __init__(self):
        self.llm_client = get_chat_llm(llm_settings)
        # add logic to init flow message include flow function and flow input
        self.flow_message = {}
        self.flow_message["rag_raw"] = RAGRAW_FLOW_PROMPT
        self.flow_message["rag_vector_only"] = RAGVECTORONLY_FLOW_PROMPT
        self.flow_message["rag_graph_only"] = RAGGRAPHONLY_FLOW_PROMPT
        self.flow_message["rag_graph_vector"] = RAGGRAPHVECTOR_FLOW_PROMPT
        return

    async def detect(self, query: str, flow_list: list[str]):
        # INSERT_YOUR_CODE
        # Compose the prompt for the LLM by filling in the user query and tool descriptions
        tool_descs = []
        for flow in flow_list:
            if flow in self.flow_message:
                tool_descs.append(self.flow_message[flow])
        tools_str = "\n\n".join(tool_descs)
        prompt = INTENT_DETECTOR_PROMPT.replace("{{tool_list}}", tools_str)
        prompt = prompt.replace("{{user_query}}", query)
        result = await self.llm_client.agenerate(prompt=prompt)
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
