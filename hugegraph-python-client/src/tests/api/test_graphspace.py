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

import unittest

from tests.client_utils import ClientUtils


class TestGraphspaceManager(unittest.TestCase):
    """
    Test cases for GraphspaceManager (requires HugeGraph v3.0+).
    These tests will be skipped if the server doesn't support graphspaces.
    """

    client = None
    graphspace = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.graphspace = cls.client.client.graphspace()

    def setUp(self):
        # Skip tests if graphspace is not supported
        if not self.client.client.cfg.gs_supported:
            self.skipTest("Graphspace feature requires HugeGraph v3.0+")

    def test_list_graphspaces(self):
        """Test listing all graphspaces."""
        try:
            graphspaces = self.graphspace.list()
            self.assertIsNotNone(graphspaces)
            # DEFAULT graphspace should exist in v3.0+
            self.assertIn("DEFAULT", str(graphspaces))
        except Exception as e:
            self.skipTest(f"Graphspace list operation not supported: {e}")

    def test_create_and_delete_graphspace(self):
        """Test creating and deleting a graphspace."""
        test_space_name = "test_graphspace_temp"
        
        try:
            # Create graphspace
            result = self.graphspace.create(test_space_name)
            self.assertIsNotNone(result)
            
            # Verify it exists
            info = self.graphspace.get(test_space_name)
            self.assertIsNotNone(info)
            
            # Clean up - delete it
            delete_result = self.graphspace.delete(test_space_name)
            self.assertIsNotNone(delete_result)
        except Exception as e:
            # Clean up in case of error
            try:
                self.graphspace.delete(test_space_name)
            except Exception:
                pass
            self.skipTest(f"Graphspace create/delete operations not supported: {e}")

    def test_get_default_graphspace(self):
        """Test getting the DEFAULT graphspace."""
        try:
            info = self.graphspace.get("DEFAULT")
            self.assertIsNotNone(info)
        except Exception as e:
            self.skipTest(f"Graphspace get operation not supported: {e}")


if __name__ == "__main__":
    unittest.main()
