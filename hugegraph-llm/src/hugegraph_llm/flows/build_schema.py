from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.nodes.llm_node.schema_build import SchemaBuildNode
from hugegraph_llm.utils.log import log

import json
from PyCGraph import GPipeline


class BuildSchemaFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(
        self,
        prepared_input: WkFlowInput,
        texts=None,
        query_examples=None,
        few_shot_schema=None,
    ):
        prepared_input.texts = texts
        # Optional fields packed into wk_input for SchemaBuildNode
        # Keep raw values; node will parse if strings
        prepared_input.query_examples = query_examples
        prepared_input.few_shot_schema = few_shot_schema
        return

    def build_flow(self, texts=None, query_examples=None, few_shot_schema=None):
        pipeline = GPipeline()
        prepared_input = WkFlowInput()
        self.prepare(
            prepared_input,
            texts=texts,
            query_examples=query_examples,
            few_shot_schema=few_shot_schema,
        )

        pipeline.createGParam(prepared_input, "wkflow_input")
        pipeline.createGParam(WkFlowState(), "wkflow_state")

        schema_build_node = SchemaBuildNode()
        pipeline.registerGElement(schema_build_node, set(), "schema_build")

        return pipeline

    def post_deal(self, pipeline=None):
        res = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()["schema"]
        try:
            formatted_schema = json.dumps(res, ensure_ascii=False, indent=2)
            return formatted_schema
        except (TypeError, ValueError) as e:
            log.error("Failed to format schema: %s", e)
            return str(res)
