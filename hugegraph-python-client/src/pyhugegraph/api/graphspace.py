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


class GraphspaceManager(HugeParamsBase):
    """
    Manager for HugeGraph graphspace operations (requires HugeGraph v3.0+).
    Graphspaces provide isolation between different graph collections.
    """

    @router.http("POST", "/graphspaces")
    def create(self, name: str) -> dict:
        """
        Create a new graphspace.

        Args:
            name (str): Name of the graphspace to create.

        Returns:
            dict: Response containing graphspace creation result.
        """
        return self._invoke_request(
            validator=ResponseValidation("text"),
            data=json.dumps({"name": name}),
        )

    @router.http("GET", "/graphspaces/{name}")
    def get(self, name: str) -> dict:
        """
        Get details of a specific graphspace.

        Args:
            name (str): Name of the graphspace.

        Returns:
            dict: Graphspace details.
        """
        return self._invoke_request(
            placeholders={"name": name},
            validator=ResponseValidation("text"),
        )

    @router.http("GET", "/graphspaces")
    def list(self) -> dict:
        """
        List all graphspaces.

        Returns:
            dict: List of all graphspaces.
        """
        return self._invoke_request(validator=ResponseValidation("text"))

    @router.http("DELETE", "/graphspaces/{name}")
    def delete(self, name: str) -> dict:
        """
        Delete a graphspace.

        Args:
            name (str): Name of the graphspace to delete.

        Returns:
            dict: Response containing deletion result.
        """
        return self._invoke_request(
            placeholders={"name": name},
            validator=ResponseValidation("text"),
        )

    @router.http("PUT", "/graphspaces/{name}")
    def update(self, name: str, new_name: str = None, description: str = None) -> dict:
        """
        Update graphspace properties.

        Args:
            name (str): Current name of the graphspace.
            new_name (str, optional): New name for the graphspace.
            description (str, optional): Description for the graphspace.

        Returns:
            dict: Response containing update result.
        """
        data = {}
        if new_name:
            data["name"] = new_name
        if description:
            data["description"] = description

        return self._invoke_request(
            placeholders={"name": name},
            validator=ResponseValidation("text"),
            data=json.dumps(data) if data else None,
        )
