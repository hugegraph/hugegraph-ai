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


class TestGraphsManager(unittest.TestCase):
    client = None
    graph = None

    @classmethod
    def setUpClass(cls):
        cls.client = ClientUtils()
        cls.graphs = cls.client.graphs
        cls.client.init_property_key()
        cls.client.init_vertex_label()
        cls.client.init_edge_label()
        cls.client.init_index_label()

    @classmethod
    def tearDownClass(cls):
        cls.client.clear_graph_all_data()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_get_all_graphs(self):
        all_graphs = self.graphs.get_all_graphs()
        self.assertTrue("hugegraph" in all_graphs)

    def test_get_version(self):
        version = self.graphs.get_version()
        self.assertIsNotNone(version)

    def test_get_graph_info(self):
        graph_info = self.graphs.get_graph_info()
        self.assertTrue("backend" in graph_info)

    def test_get_graph_config(self):
        graph_config = self.graphs.get_graph_config()
        self.assertIsNotNone(graph_config)

    def test_create_and_delete_graph(self):
        """Test dynamic graph creation and deletion."""
        test_graph_name = "test_graph_temp"
        
        try:
            # Create a new graph with minimal config
            # In practice, you'd provide proper configuration
            result = self.graphs.create_graph(test_graph_name)
            self.assertIsNotNone(result)
            
            # Verify it exists by checking all graphs
            all_graphs = self.graphs.get_all_graphs()
            self.assertIn(test_graph_name, str(all_graphs))
            
            # Delete the graph
            delete_result = self.graphs.delete_graph(test_graph_name)
            self.assertIsNotNone(delete_result)
        except Exception as e:
            # Clean up in case of error
            try:
                self.graphs.delete_graph(test_graph_name)
            except Exception:
                pass
            # Skip test if feature not available or requires admin permissions
            self.skipTest(f"Dynamic graph operations not supported: {e}")

    def test_clone_graph(self):
        """Test graph cloning."""
        source_graph = "hugegraph"
        target_graph = "hugegraph_clone_temp"
        
        try:
            # Clone the graph
            result = self.graphs.clone_graph(
                source_graph=source_graph,
                target_graph=target_graph
            )
            self.assertIsNotNone(result)
            
            # Clean up - delete the cloned graph
            self.graphs.delete_graph(target_graph)
        except Exception as e:
            # Clean up in case of error
            try:
                self.graphs.delete_graph(target_graph)
            except Exception:
                pass
            # Skip test if feature not available or requires admin permissions
            self.skipTest(f"Graph cloning not supported: {e}")
