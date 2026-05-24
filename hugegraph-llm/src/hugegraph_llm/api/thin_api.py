# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from typing import Any

from fastapi import APIRouter, status

from hugegraph_llm.api.models.rag_requests import (
    GraphExtractRequest,
    GraphImportRequest,
    VidEmbeddingsRefreshRequest,
)
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.log import log

thin_router = APIRouter()


def _success(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _flow_error(exc: Exception) -> dict[str, Any]:
    log.error("Thin API flow execution failed: %s", exc, exc_info=True)
    return {
        "ok": False,
        "data": None,
        "error": {
            "type": "FLOW_EXECUTION_FAILED",
            "message": str(exc),
        },
    }


@thin_router.post("/thin/graph-extract", status_code=status.HTTP_200_OK)
def graph_extract_api(req: GraphExtractRequest):
    try:
        result = SchedulerSingleton.get_instance().schedule_flow(
            FlowName.GRAPH_EXTRACT,
            req.schema,
            req.text,
            req.example_prompt,
            "property_graph",
            req.language,
        )
        return _success(result)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _flow_error(exc)


@thin_router.post("/thin/graph-import", status_code=status.HTTP_200_OK)
def graph_import_api(req: GraphImportRequest):
    try:
        result = SchedulerSingleton.get_instance().schedule_flow(
            FlowName.IMPORT_GRAPH_DATA,
            req.data,
            req.schema,
        )
        return _success(result)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _flow_error(exc)


@thin_router.post("/thin/vid-embeddings/refresh", status_code=status.HTTP_200_OK)
def vid_embeddings_refresh_api(_req: VidEmbeddingsRefreshRequest):
    try:
        result = SchedulerSingleton.get_instance().schedule_flow(FlowName.UPDATE_VID_EMBEDDINGS)
        return _success(result)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _flow_error(exc)


@thin_router.get("/thin/graph-index-info", status_code=status.HTTP_200_OK)
def graph_index_info_api():
    try:
        result = SchedulerSingleton.get_instance().schedule_flow(FlowName.GET_GRAPH_INDEX_INFO)
        return _success(result)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _flow_error(exc)
