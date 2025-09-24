from PyCGraph import CStatus, GPipeline
from hugegraph_llm.flows.common import BaseFlow, WkFlowInput
from hugegraph_llm.nodes.hugegraph_node.fetch_graph_data import FetchGraphDataNode
from hugegraph_llm.nodes.index_node.build_semantic_index import BuildSemanticIndexNode
from hugegraph_llm.state.ai_state import WkFlowState


class UpdateVidEmbeddingsFlows(BaseFlow):
    def prepare(self, prepared_input: WkFlowInput):
        return CStatus()

    def build_flow(self):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        # prepare input data
        self.prepare(prepared_input)

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        fetch_node = FetchGraphDataNode()
        build_node = BuildSemanticIndexNode()
        pipeline.registerGElement(fetch_node, set(), "fetch_node")
        pipeline.registerGElement(build_node, {fetch_node}, "build_node")

        return pipeline

    def post_deal(self, pipeline):
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        removed_num = res["removed_vid_vector_num"]
        added_num = res["added_vid_vector_num"]
        return f"Removed {removed_num} vectors, added {added_num} vectors."
