from PyCGraph import CStatus
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState


class Commit2GraphNode(BaseNode):
    commit_to_graph_op: Commit2Graph
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        data_json = self.wk_input.data_json if self.wk_input.data_json else None
        if data_json:
            self.context.assign_from_json(data_json)
        self.commit_to_graph_op = Commit2Graph()
        return CStatus()

    def operator_schedule(self, data_json):
        return self.commit_to_graph_op.run(data_json)
