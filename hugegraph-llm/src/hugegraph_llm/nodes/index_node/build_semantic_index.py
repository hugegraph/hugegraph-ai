from PyCGraph import CStatus
from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.embeddings.init_embedding import get_embedding
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.index_op.build_semantic_index import BuildSemanticIndex
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class BuildSemanticIndexNode(BaseNode):
    build_semantic_index_op: BuildSemanticIndex
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        self.build_semantic_index_op = BuildSemanticIndex(get_embedding(llm_settings))
        return CStatus()

    def operator_schedule(self, data_json):
        return self.build_semantic_index_op.run(data_json)
