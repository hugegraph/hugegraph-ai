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

    def get_all_graphs(self) -> dict:
        """
        List all graphs in the graphspace.
        
        API: GET /graphspaces/{graphspace}/graphs
        
        Returns:
            dict: Response containing list of graphs.
        """
        # For 1.7.0+, use graphspace-aware path
        if self._sess.cfg.gs_supported:
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs"
        else:
            # Legacy path for older versions
            url = "/graphs"
        return self._sess.request(url, "GET", validator=ResponseValidation("text"))

    @router.http("GET", "/versions")
    def get_version(self) -> dict:
        return self._invoke_request(validator=ResponseValidation("text"))

    def get_graph_info(self) -> dict:
        """
        Get information about the current graph.
        
        API: GET /graphspaces/{graphspace}/graphs/{graph}
        
        Returns:
            dict: Response containing graph information (name, backend, etc.).
        """
        # For 1.7.0+, use graphspace-aware path
        if self._sess.cfg.gs_supported:
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs/{self._sess.cfg.graph_name}"
        else:
            # Legacy path - use relative path which resolves to /graphs/{graph}/
            url = ""
        return self._sess.request(url, "GET", validator=ResponseValidation("text"))

    def clear_graph_all_data(self) -> dict:
        """
        Clear all data from the current graph including schema, vertices, edges, and indexes.
        
        API: DELETE /graphspaces/{graphspace}/graphs/{graph}/clear?confirm_message=...
        
        Returns:
            dict: Response (HTTP 204).
        """
        from urllib.parse import quote
        confirm_msg = quote("I'm sure to delete all data")
        
        if self._sess.cfg.gs_supported:
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs/{self._sess.cfg.graph_name}/clear?confirm_message={confirm_msg}"
            method = "DELETE"
        else:
            # Legacy path and method
            url = f"clear?confirm_message={confirm_msg}"
            method = "DELETE"
        
        return self._sess.request(url, method, validator=ResponseValidation("text"))

    def get_graph_config(self) -> dict:
        """
        Get configuration of the current graph.
        
        API: GET /graphspaces/{graphspace}/graphs/{graph}/conf
        
        Returns:
            dict: Response containing graph configuration.
        """
        # For 1.7.0+, use graphspace-aware path
        if self._sess.cfg.gs_supported:
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs/{self._sess.cfg.graph_name}/conf"
        else:
            # Legacy relative path
            url = "conf"
        return self._sess.request(url, "GET", validator=ResponseValidation("text"))

    def create_graph(self, graph_name: str, config_dict: dict = None) -> dict:
        """
        Create a new graph dynamically.
        
        API (1.7.0+): POST /graphspaces/{graphspace}/graphs/{graph}
        Request body: JSON configuration
        
        Note: For HugeGraph 1.5.0 and earlier, use text/plain format instead of JSON.

        Args:
            graph_name (str): Name of the graph to create.
            config_dict (dict, optional): Graph configuration as dictionary.
                Example:
                {
                    "gremlin.graph": "org.apache.hugegraph.HugeFactory",
                    "backend": "rocksdb",
                    "serializer": "binary",
                    "store": "hugegraph",
                    "rocksdb.data_path": "./rks-data-xx",
                    "rocksdb.wal_path": "./rks-data-xx"
                }

        Returns:
            dict: Response containing graph creation result with name and backend.
        """
        if self._sess.cfg.gs_supported:
            # 1.7.0+ uses graphspace-aware path with JSON body
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs/{graph_name}"
            data = json.dumps(config_dict) if config_dict else None
        else:
            # Legacy path for older versions (uses text/plain)
            url = f"/graphs/{graph_name}"
            data = config_dict if config_dict else None
        
        return self._sess.request(
            url,
            "POST",
            validator=ResponseValidation("text"),
            data=data,
        )

    def delete_graph(self, graph_name: str, confirm_message: str = "I'm sure to drop the graph") -> dict:
        """
        Delete a graph and all its data.
        
        API (1.7.0+): DELETE /graphspaces/{graphspace}/graphs/{graph}?confirm_message=...

        Args:
            graph_name (str): Name of the graph to delete.
            confirm_message (str): Confirmation message to prevent accidental deletion.
                Default is "I'm sure to drop the graph".

        Returns:
            dict: Response containing deletion result (HTTP 204).
        """
        from urllib.parse import quote
        
        if self._sess.cfg.gs_supported:
            # 1.7.0+ uses graphspace-aware path
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs/{graph_name}?confirm_message={quote(confirm_message)}"
        else:
            # Legacy path
            url = f"/graphs/{graph_name}?confirm_message={quote(confirm_message)}"
        
        return self._sess.request(
            url,
            "DELETE",
            validator=ResponseValidation("text"),
        )

    def clone_graph(
        self,
        source_graph: str,
        target_graph: str,
        config_dict: dict = None,
    ) -> dict:
        """
        Clone a graph from an existing graph.
        
        API (1.7.0+): POST /graphspaces/{graphspace}/graphs/{new_graph}?clone_graph_name={source}
        Request body: Optional JSON configuration to override
        
        Note: For HugeGraph 1.5.0 and earlier, use text/plain format instead of JSON.

        Args:
            source_graph (str): Name of the source graph to clone from.
            target_graph (str): Name of the new graph to create.
            config_dict (dict, optional): Configuration dictionary to override settings in cloned graph.
                If not provided, uses configuration from source graph.
                Example:
                {
                    "gremlin.graph": "org.apache.hugegraph.HugeFactory",
                    "backend": "rocksdb",
                    "serializer": "binary",
                    "store": "hugegraph_clone",
                    "rocksdb.data_path": "./rks-data-clone",
                    "rocksdb.wal_path": "./rks-data-clone"
                }

        Returns:
            dict: Response containing clone operation result with name and backend.
        """
        if self._sess.cfg.gs_supported:
            # 1.7.0+ uses graphspace-aware path with JSON body
            url = f"/graphspaces/{self._sess.cfg.graphspace}/graphs/{target_graph}?clone_graph_name={source_graph}"
            data = json.dumps(config_dict) if config_dict else None
        else:
            # Legacy path (uses text/plain)
            url = f"/graphs/{target_graph}?clone_graph_name={source_graph}"
            data = config_dict if config_dict else None
        
        return self._sess.request(
            url,
            "POST",
            validator=ResponseValidation("text"),
            data=data,
        )
