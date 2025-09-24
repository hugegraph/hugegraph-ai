from hugegraph_llm.nodes.base_node import BaseNode
from PyCGraph import CStatus
from hugegraph_llm.operators.document_op.chunk_split import ChunkSplit
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class ChunkSplitNode(BaseNode):
    chunk_split_op: ChunkSplit
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        if (
            self.wk_input.texts is None
            or self.wk_input.language is None
            or self.wk_input.split_type is None
        ):
            return CStatus(-1, "Error occurs when prepare for workflow input")
        texts = self.wk_input.texts
        language = self.wk_input.language
        split_type = self.wk_input.split_type
        if isinstance(texts, str):
            texts = [texts]
        self.chunk_split_op = ChunkSplit(texts, split_type, language)
        return CStatus()

    def operator_schedule(self, data_json):
        return self.chunk_split_op.run(data_json)
