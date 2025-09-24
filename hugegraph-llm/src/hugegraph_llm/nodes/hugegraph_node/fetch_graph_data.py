from PyCGraph import CStatus
from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.hugegraph_utils import get_hg_client


class FetchGraphDataNode(BaseNode):
    fetch_graph_data_op: FetchGraphData
    context: WkFlowState = None
    wk_input: WkFlowInput = None

    def node_init(self):
        self.fetch_graph_data_op = FetchGraphData(get_hg_client())
        return CStatus()

    def operator_schedule(self, data_json):
        return self.fetch_graph_data_op.run(data_json)
