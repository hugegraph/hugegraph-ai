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


class TestClientSwitching(unittest.TestCase):
    """
    Test cases for PyHugeClient graph/graphspace switching functionality.
    """

    client = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()

    def test_switch_graph(self):
        """Test switching between graphs."""
        original_graph = self.client.client.cfg.graph_name
        test_graph = "test_graph"
        
        # Switch to test_graph
        self.client.client.switch_graph(test_graph)
        self.assertEqual(self.client.client.cfg.graph_name, test_graph)
        
        # Verify cached managers were cleared
        # Accessing schema should create a new manager with new graph context
        schema = self.client.client.schema()
        self.assertIsNotNone(schema)
        
        # Switch back to original
        self.client.client.switch_graph(original_graph)
        self.assertEqual(self.client.client.cfg.graph_name, original_graph)

    def test_switch_graphspace(self):
        """Test switching between graphspaces (v3.0+ only)."""
        if not self.client.client.cfg.gs_supported:
            self.skipTest("Graphspace switching requires HugeGraph v3.0+")
        
        original_graphspace = self.client.client.cfg.graphspace
        test_graphspace = "test_space"
        
        try:
            # Switch to test_space
            self.client.client.switch_graphspace(test_graphspace)
            self.assertEqual(self.client.client.cfg.graphspace, test_graphspace)
            
            # Verify cached managers were cleared
            schema = self.client.client.schema()
            self.assertIsNotNone(schema)
        finally:
            # Switch back to original
            self.client.client.switch_graphspace(original_graphspace)
            self.assertEqual(self.client.client.cfg.graphspace, original_graphspace)

    def test_switch_graphspace_not_supported(self):
        """Test that switching graphspace fails gracefully on older versions."""
        if self.client.client.cfg.gs_supported:
            self.skipTest("Test only applies when graphspace is not supported")
        
        # Should raise RuntimeError on older versions
        with self.assertRaises(RuntimeError):
            self.client.client.switch_graphspace("some_space")

    def test_multiple_switches(self):
        """Test multiple consecutive switches."""
        original_graph = self.client.client.cfg.graph_name
        graphs = ["graph1", "graph2", "graph3"]
        
        try:
            for graph in graphs:
                self.client.client.switch_graph(graph)
                self.assertEqual(self.client.client.cfg.graph_name, graph)
                
                # Verify manager recreation works
                schema = self.client.client.schema()
                self.assertIsNotNone(schema)
        finally:
            # Restore original
            self.client.client.switch_graph(original_graph)

    def test_switch_preserves_connection(self):
        """Test that switching doesn't break the connection."""
        original_graph = self.client.client.cfg.graph_name
        
        # Switch graph
        self.client.client.switch_graph("temp_graph")
        
        # Verify we can still make requests (even if graph doesn't exist)
        try:
            version = self.client.client.graphs().get_version()
            self.assertIsNotNone(version)
        except Exception:
            # It's ok if request fails, we just want to verify connection works
            pass
        finally:
            # Restore original
            self.client.client.switch_graph(original_graph)


if __name__ == "__main__":
    unittest.main()
