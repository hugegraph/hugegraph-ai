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

"""
Example demonstrating new features for HugeGraph v3.0+ (1.7.0 API):
- Graphspace management
- Dynamic graph creation
- Graph/graphspace switching
"""

from pyhugegraph.client import PyHugeClient


def example_graphspace_management():
    """Demonstrate graphspace management operations."""
    print("\n=== Graphspace Management ===")
    
    client = PyHugeClient(
        url="http://127.0.0.1:8080",
        user="admin",
        pwd="admin",
        graph="hugegraph",
        graphspace="DEFAULT"
    )
    
    # List all graphspaces
    print("Listing all graphspaces:")
    try:
        graphspaces = client.graphspace().list()
        print(f"Graphspaces: {graphspaces}")
    except Exception as e:
        print(f"Note: {e}")
    
    # Create a new graphspace (if supported)
    try:
        print("\nCreating new graphspace 'test_space':")
        result = client.graphspace().create("test_space")
        print(f"Result: {result}")
        
        # Get graphspace details
        print("\nGetting graphspace details:")
        info = client.graphspace().get("test_space")
        print(f"Info: {info}")
        
    except Exception as e:
        print(f"Note: {e}")


def example_dynamic_graph_management():
    """Demonstrate dynamic graph creation and management."""
    print("\n=== Dynamic Graph Management ===")
    
    client = PyHugeClient(
        url="http://127.0.0.1:8080",
        user="admin",
        pwd="admin",
        graph="hugegraph",
        graphspace="DEFAULT"
    )
    
    # Create a new graph
    try:
        print("Creating new graph 'my_graph':")
        result = client.graphs().create_graph("my_graph")
        print(f"Result: {result}")
    except Exception as e:
        print(f"Note: {e}")
    
    # List all graphs
    try:
        print("\nListing all graphs:")
        graphs = client.graphs().get_all_graphs()
        print(f"Graphs: {graphs}")
    except Exception as e:
        print(f"Note: {e}")
    
    # Clone a graph
    try:
        print("\nCloning graph:")
        result = client.graphs().clone_graph(
            source_graph="hugegraph",
            target_graph="hugegraph_copy",
            clone_schema=True,
            clone_data=False
        )
        print(f"Result: {result}")
    except Exception as e:
        print(f"Note: {e}")


def example_graph_switching():
    """Demonstrate switching between graphs and graphspaces."""
    print("\n=== Graph/Graphspace Switching ===")
    
    client = PyHugeClient(
        url="http://127.0.0.1:8080",
        user="admin",
        pwd="admin",
        graph="hugegraph",
        graphspace="DEFAULT"
    )
    
    # Check initial context
    print(f"Initial context: {client.cfg.graphspace}/{client.cfg.graph_name}")
    
    # Get schema for initial graph
    try:
        schema = client.schema()
        labels = schema.getVertexLabels()
        print(f"Vertex labels in {client.cfg.graph_name}: {labels}")
    except Exception as e:
        print(f"Note: {e}")
    
    # Switch to a different graph
    try:
        print("\nSwitching to 'my_graph':")
        client.switch_graph("my_graph")
        print(f"Current context: {client.cfg.graphspace}/{client.cfg.graph_name}")
        
        # Schema is automatically recreated for new graph
        schema = client.schema()
        labels = schema.getVertexLabels()
        print(f"Vertex labels in {client.cfg.graph_name}: {labels}")
    except Exception as e:
        print(f"Note: {e}")
    
    # Switch graphspace (if supported)
    try:
        print("\nSwitching to 'test_space':")
        client.switch_graphspace("test_space")
        print(f"Current context: {client.cfg.graphspace}/{client.cfg.graph_name}")
    except Exception as e:
        print(f"Note: {e}")
    
    # Switch back
    print("\nSwitching back to DEFAULT/hugegraph:")
    try:
        client.switch_graphspace("DEFAULT")
        client.switch_graph("hugegraph")
        print(f"Current context: {client.cfg.graphspace}/{client.cfg.graph_name}")
    except Exception as e:
        print(f"Note: {e}")


def example_combined_workflow():
    """Demonstrate a complete workflow using new features."""
    print("\n=== Combined Workflow Example ===")
    
    # Initialize client
    client = PyHugeClient(
        url="http://127.0.0.1:8080",
        user="admin",
        pwd="admin",
        graph="hugegraph",
        graphspace="DEFAULT"
    )
    
    print("Step 1: Check server version")
    try:
        version = client.graphs().get_version()
        print(f"Server version: {version}")
        print(f"Graphspace support: {client.cfg.gs_supported}")
    except Exception as e:
        print(f"Note: {e}")
    
    print("\nStep 2: List existing graphs")
    try:
        graphs = client.graphs().get_all_graphs()
        print(f"Available graphs: {graphs}")
    except Exception as e:
        print(f"Note: {e}")
    
    print("\nStep 3: Operate on multiple graphs with single client")
    graphs_to_check = ["hugegraph", "my_graph", "test_graph"]
    for graph_name in graphs_to_check:
        try:
            client.switch_graph(graph_name)
            info = client.graphs().get_graph_info()
            print(f"Graph '{graph_name}' info: {info.get('backend', 'N/A')}")
        except Exception as e:
            print(f"Graph '{graph_name}': {e}")


if __name__ == "__main__":
    print("HugeGraph v3.0+ Python Client Examples")
    print("=" * 50)
    
    # Run examples
    example_graphspace_management()
    example_dynamic_graph_management()
    example_graph_switching()
    example_combined_workflow()
    
    print("\n" + "=" * 50)
    print("Examples completed!")
    print("\nNote: Some operations may fail if:")
    print("- HugeGraph server is not running")
    print("- Server version is < 3.0 (graphspace features)")
    print("- Graphs/graphspaces don't exist")
