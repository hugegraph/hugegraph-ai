#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import json

from hugegraph_llm.flows.common import BaseFlow
from hugegraph_llm.flows.utils import prepare_schema
from hugegraph_llm.state.ai_state import WkFlowInput
from hugegraph_llm.utils.log import log


class ImportGraphDataFlow(BaseFlow):
    def __init__(self):
        pass

    def prepare(self, prepared_input: WkFlowInput, data, schema):
        data_json = json.loads(data.strip())
        log.debug("Import graph data: %s", data)
        prepared_input.data_json = data_json
        if schema:
            error_message = prepare_schema(prepared_input, schema)
            if error_message:
                return error_message
        return

    def build_flow(self, data, schema):
        pass
