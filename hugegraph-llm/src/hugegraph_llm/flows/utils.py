import json


from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils.log import log


def prepare_schema(prepared_input: WkFlowInput, schema):
    schema = schema.strip()
    if schema.startswith("{"):
        try:
            schema = json.loads(schema)
            prepared_input.schema = schema
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON format in schema. Please check it again.")
            raise ValueError("Invalid JSON format in schema.") from exc
    else:
        log.info("Get schema '%s' from graphdb.", schema)
        prepared_input.graph_name = schema
    return
