import json

from hugegraph_llm.operators.common_op.check_schema import CheckSchemaNode
from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManagerNode
from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils.log import log


def import_schema(
    from_hugegraph=None,
    from_extraction=None,
    from_user_defined=None,
):
    if from_hugegraph:
        return SchemaManagerNode()
    elif from_user_defined:
        return CheckSchemaNode()
    elif from_extraction:
        raise NotImplementedError("Not implemented yet")
    else:
        raise ValueError("No input data / invalid schema type")


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


def get_schema_node(schema):
    schema = schema.strip()
    schema_node = None
    if schema.startswith("{"):
        try:
            schema = json.loads(schema)
            schema_node = import_schema(from_user_defined=schema)
        except json.JSONDecodeError as exc:
            log.error("Invalid JSON format in schema. Please check it again.")
            raise ValueError("Invalid JSON format in schema.") from exc
    else:
        log.info("Get schema '%s' from graphdb.", schema)
        schema_node = import_schema(from_hugegraph=schema)
    return schema_node
