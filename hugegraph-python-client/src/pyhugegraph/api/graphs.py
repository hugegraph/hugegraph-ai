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

import json

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.utils import huge_router as router
from pyhugegraph.utils.util import ResponseValidation


class GraphsManager(HugeParamsBase):

    @router.http("GET", "/graphs")
    def get_all_graphs(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    @router.http("GET", "/versions")
    def get_version(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    @router.http("GET", "")
    def get_graph_info(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    def clear_graph_all_data(self) -> dict:
        if self._sess.cfg.gs_supported:
            response = self._sess.request(
                "",
                "PUT",
                validator=ResponseValidation("text"),
                data=json.dumps({"action": "clear", "clear_schema": True}),
            )
        else:
            response = self._sess.request(
                "clear?confirm_message=I%27m+sure+to+delete+all+data",
                "DELETE",
                validator=ResponseValidation("text"),
            )
        return response

    @router.http("GET", "conf")
    def get_graph_config(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    def create_graph(self, graph_name: str, config_path: str = None) -> dict:
        """
        Create a new graph dynamically.

        Args:
            graph_name (str): Name of the graph to create.
            config_path (str, optional): Path to graph configuration file.

        Returns:
            dict: Response containing graph creation result.
        """
        if self._sess.cfg.gs_supported:
            # For v3+, use graphspace-aware endpoint
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs"
            data = {"name": graph_name}
            if config_path:
                data["config_path"] = config_path
            return self._sess.request(
                url,
                "POST",
                validator=ResponseValidation("text"),
                data=json.dumps(data),
            )
        else:
            # For older versions, graph creation typically requires server restart
            # This is a configuration-based operation
            raise NotImplementedError(
                "Dynamic graph creation is only supported in HugeGraph v3.0+. "
                "For older versions, graphs must be configured in the server configuration."
            )

    def delete_graph(self, graph_name: str) -> dict:
        """
        Delete a graph.

        Args:
            graph_name (str): Name of the graph to delete.

        Returns:
            dict: Response containing deletion result.
        """
        if self._sess.cfg.gs_supported:
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs/{graph_name}"
            return self._sess.request(
                url,
                "DELETE",
                validator=ResponseValidation("text"),
            )
        else:
            raise NotImplementedError(
                "Dynamic graph deletion is only supported in HugeGraph v3.0+."
            )

    def clone_graph(
        self,
        source_graph: str,
        target_graph: str,
        clone_schema: bool = True,
        clone_data: bool = False,
    ) -> dict:
        """
        Clone a graph (schema and optionally data).

        Args:
            source_graph (str): Name of the source graph to clone from.
            target_graph (str): Name of the target graph to create.
            clone_schema (bool): Whether to clone schema (default: True).
            clone_data (bool): Whether to clone data (default: False).

        Returns:
            dict: Response containing clone operation result.
        """
        if self._sess.cfg.gs_supported:
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs"
            data = {
                "name": target_graph,
                "clone_graph_name": source_graph,
                "clone_schema": clone_schema,
                "clone_data": clone_data,
            }
            return self._sess.request(
                url,
                "POST",
                validator=ResponseValidation("text"),
                data=json.dumps(data),
            )
        else:
            raise NotImplementedError(
                "Graph cloning is only supported in HugeGraph v3.0+."
            )
