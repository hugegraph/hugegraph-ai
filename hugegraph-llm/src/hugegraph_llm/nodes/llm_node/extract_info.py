from PyCGraph import CStatus
from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.llms.init_llm import get_chat_llm
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.llm_op.info_extract import InfoExtract
from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class ExtractNode(BaseNode):
    property_graph_extract: PropertyGraphExtract
    info_extract: InfoExtract
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    extract_type: str = None

    def node_init(self):
        llm = get_chat_llm(llm_settings)
        if self.wk_input.example_prompt is None:
            return CStatus(-1, "Error occurs when prepare for workflow input")
        example_prompt = self.wk_input.example_prompt
        extract_type = self.wk_input.extract_type
        self.extract_type = extract_type
        if extract_type == "triples":
            self.info_extract = InfoExtract(llm, example_prompt)
        elif extract_type == "property_graph":
            self.property_graph_extract = PropertyGraphExtract(llm, example_prompt)
        else:
            raise ValueError(f"Unsupported extract_type: {extract_type}")
        return CStatus()

    def operator_schedule(self, data_json):
        if self.extract_type == "triples":
            return self.info_extract.run(data_json)
        elif self.extract_type == "property_graph":
            return self.property_graph_extract.run(data_json)
