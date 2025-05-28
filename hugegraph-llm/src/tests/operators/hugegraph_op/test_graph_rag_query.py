import unittest
from unittest.mock import patch, MagicMock

from hugegraph_llm.operators.hugegraph_op.graph_rag_query import GraphRAGQuery
from hugegraph_llm.config.llm_config import LLMConfig


class TestGraphRAGQueryLengthCheck(unittest.TestCase):

    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.GremlinGenerator')
    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.PyHugeClient')
    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.LLMConfig')
    def test_query_length_within_limits(self, MockLLMConfig, MockPyHugeClient, MockGremlinGenerator):
        # Configure mock LLMConfig
        mock_llm_config_instance = MockLLMConfig.return_value
        mock_llm_config_instance.rag_query_max_length = 50

        # Mock PyHugeClient and GremlinGenerator instances
        MockPyHugeClient.return_value = MagicMock()
        MockGremlinGenerator.return_value = MagicMock()

        # Create GraphRAGQuery instance
        # Provide minimal mocks for llm and embedding if necessary for __init__
        graph_rag_query_instance = GraphRAGQuery(llm=MagicMock(), embedding=MagicMock())

        # Prepare context
        context = {"query": "This is a short query."}

        # Mock methods that would be called after the length check
        graph_rag_query_instance.init_client = MagicMock()
        graph_rag_query_instance._gremlin_generate_query = MagicMock(return_value=context)
        graph_rag_query_instance._subgraph_query = MagicMock(return_value=context)


        # Call run method and assert no ValueError is raised
        try:
            graph_rag_query_instance.run(context)
            self.assertTrue(True)  # If no exception, test passes
        except ValueError:
            self.fail("ValueError raised unexpectedly for query within limits.")
        
        # Assert init_client was called (it's called after the check)
        graph_rag_query_instance.init_client.assert_called_once_with(context)


    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.log')
    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.GremlinGenerator')
    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.PyHugeClient')
    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.LLMConfig')
    def test_query_length_exceeds_limits(self, MockLLMConfig, MockPyHugeClient, MockGremlinGenerator, mock_log):
        # Configure mock LLMConfig
        mock_llm_config_instance = MockLLMConfig.return_value
        mock_llm_config_instance.rag_query_max_length = 10

        # Mock PyHugeClient and GremlinGenerator instances
        MockPyHugeClient.return_value = MagicMock()
        MockGremlinGenerator.return_value = MagicMock()

        # Create GraphRAGQuery instance
        graph_rag_query_instance = GraphRAGQuery(llm=MagicMock(), embedding=MagicMock())

        # Prepare context
        query_text = "This query is definitely too long."
        context = {"query": query_text}

        # Call run method and assert ValueError is raised
        with self.assertRaises(ValueError) as cm:
            graph_rag_query_instance.run(context)

        expected_error_message = f"Error: Query is too long. Maximum allowed length is 10 characters."
        self.assertEqual(str(cm.exception), expected_error_message)
        mock_log.error.assert_called_once_with(f"Query exceeds maximum length of 10 characters.")
        
        # Ensure init_client was not called because the error should be raised before
        graph_rag_query_instance.init_client = MagicMock() # Assign a mock to check if it's called
        try:
            graph_rag_query_instance.run(context) 
        except ValueError:
            pass # Expected
        graph_rag_query_instance.init_client.assert_not_called()


    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.GremlinGenerator')
    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.PyHugeClient')
    @patch('hugegraph_llm.operators.hugegraph_op.graph_rag_query.LLMConfig')
    def test_query_length_equal_to_limits(self, MockLLMConfig, MockPyHugeClient, MockGremlinGenerator):
        # Configure mock LLMConfig
        mock_llm_config_instance = MockLLMConfig.return_value
        mock_llm_config_instance.rag_query_max_length = 20

        # Mock PyHugeClient and GremlinGenerator instances
        MockPyHugeClient.return_value = MagicMock()
        MockGremlinGenerator.return_value = MagicMock()

        # Create GraphRAGQuery instance
        graph_rag_query_instance = GraphRAGQuery(llm=MagicMock(), embedding=MagicMock())

        # Prepare context
        context = {"query": "This query is twenty."} # Length is 20

        # Mock methods that would be called after the length check
        graph_rag_query_instance.init_client = MagicMock()
        # Assume _subgraph_query is the default path if _gremlin_generate_query doesn't populate results
        graph_rag_query_instance._gremlin_generate_query = MagicMock(return_value=context)
        graph_rag_query_instance._subgraph_query = MagicMock(return_value=context)

        # Call run method and assert no ValueError is raised
        try:
            graph_rag_query_instance.run(context)
            self.assertTrue(True) # If no exception, test passes
        except ValueError:
            self.fail("ValueError raised unexpectedly for query with length equal to limits.")

        # Assert init_client was called (it's called after the check)
        graph_rag_query_instance.init_client.assert_called_once_with(context)

if __name__ == '__main__':
    unittest.main()
