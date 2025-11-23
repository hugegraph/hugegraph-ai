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

    def create_graph(self, graph_name: str, config_text: str = None) -> dict:
        """
        Create a new graph dynamically.
        
        According to HugeGraph API: POST /graphs/{graph_name}
        The request body should be configuration properties in text/plain format.

        Args:
            graph_name (str): Name of the graph to create.
            config_text (str, optional): Graph configuration as text (properties format).
                Example:
                    gremlin.graph=org.apache.hugegraph.HugeFactory
                    backend=rocksdb
                    serializer=binary
                    store=hugegraph2
                    rocksdb.data_path=./rks-data
                    rocksdb.wal_path=./rks-data

        Returns:
            dict: Response containing graph creation result with name and backend.
        """
        # Graph creation uses absolute path /graphs/{name}
        url = f"/graphs/{graph_name}"
        
        if config_text:
            # Configuration provided as text/plain
            return self._sess.request(
                url,
                "POST",
                validator=ResponseValidation("text"),
                data=config_text,
            )
        else:
            # No configuration provided - use default or minimal config
            return self._sess.request(
                url,
                "POST",
                validator=ResponseValidation("text"),
            )

    def delete_graph(self, graph_name: str, confirm_message: str = "I'm sure to drop the graph") -> dict:
        """
        Delete a graph and all its data.
        
        According to HugeGraph API: DELETE /graphs/{graph_name}?confirm_message=...

        Args:
            graph_name (str): Name of the graph to delete.
            confirm_message (str): Confirmation message to prevent accidental deletion.
                Default is "I'm sure to drop the graph".

        Returns:
            dict: Response containing deletion result (HTTP 204).
        """
        # Graph deletion uses absolute path with confirmation
        from urllib.parse import quote
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
        config_text: str = None,
    ) -> dict:
        """
        Clone a graph from an existing graph.
        
        According to HugeGraph API: POST /graphs/{new_graph}?clone_graph_name={source}
        The request body can optionally contain configuration to override.

        Args:
            source_graph (str): Name of the source graph to clone from.
            target_graph (str): Name of the new graph to create.
            config_text (str, optional): Configuration text to override settings in cloned graph.
                If not provided, uses configuration from source graph.
                Example:
                    gremlin.graph=org.apache.hugegraph.HugeFactory
                    backend=rocksdb
                    serializer=binary
                    store=hugegraph_clone
                    rocksdb.data_path=./rks-data-clone
                    rocksdb.wal_path=./rks-data-clone

        Returns:
            dict: Response containing clone operation result with name and backend.
        """
        # Graph cloning uses absolute path with query parameter
        url = f"/graphs/{target_graph}?clone_graph_name={source_graph}"
        
        if config_text:
            # Configuration override provided as text/plain
            return self._sess.request(
                url,
                "POST",
                validator=ResponseValidation("text"),
                data=config_text,
            )
        else:
            # No configuration override - use source graph config
            return self._sess.request(
                url,
                "POST",
                validator=ResponseValidation("text"),
            )
