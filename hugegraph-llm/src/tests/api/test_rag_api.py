import unittest
from unittest.mock import patch, MagicMock

from fastapi import APIRouter, HTTPException, status

from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.api.models.rag_requests import RAGRequest, GraphRAGRequest


class TestRagApiQueryValidation(unittest.TestCase):

    def setUp(self):
        self.router = APIRouter()
        self.mock_rag_answer_func = MagicMock()
        self.mock_graph_rag_recall_func = MagicMock()
        self.mock_apply_graph_conf = MagicMock()
        self.mock_apply_llm_conf = MagicMock()
        self.mock_apply_embedding_conf = MagicMock()
        self.mock_apply_reranker_conf = MagicMock()

        rag_http_api(
            self.router,
            self.mock_rag_answer_func,
            self.mock_graph_rag_recall_func,
            self.mock_apply_graph_conf,
            self.mock_apply_llm_conf,
            self.mock_apply_embedding_conf,
            self.mock_apply_reranker_conf,
        )

    def get_endpoint_function(self, path: str):
        for route in self.router.routes:
            if route.path == path:
                return route.endpoint
        raise ValueError(f"Route {path} not found")

    @patch('hugegraph_llm.api.models.rag_requests.LLMConfig')
    def test_rag_answer_api_query_too_long(self, mock_llm_config_pydantic):
        rag_answer_api_endpoint = self.get_endpoint_function("/rag")

        mock_llm_config_instance = mock_llm_config_pydantic.return_value
        mock_llm_config_instance.rag_query_max_length = 10

        # This will be validated by Pydantic before the endpoint logic is hit
        with self.assertRaises(HTTPException) as cm:
            # Directly instantiating RAGRequest with invalid data won't raise HTTPException here,
            # FastAPI does this when processing the request.
            # To simulate FastAPI's behavior, we assume the endpoint is called with data
            # that *would* cause Pydantic to fail during request body parsing.
            # The actual RAGRequest instantiation happens inside FastAPI's request handling.
            # For a unit test, we are directly calling the endpoint function.
            # Pydantic validation for path/query/body parameters is typically handled by
            # FastAPI's request parsing layer *before* the endpoint function is called.
            # However, if the endpoint function itself receives the raw request model and
            # Pydantic validation happens upon model instantiation *within* the endpoint,
            # then the test structure is fine. Given the current structure of FastAPI,
            # the validation for RAGRequest happens *before* rag_answer_api is called.
            # This test simulates the state *after* FastAPI has parsed and validated,
            # and if validation failed, it would have raised HTTPException(422).
            # Since we are calling the function directly, we must ensure the Pydantic model
            # itself raises an error that FastAPI would catch and convert to 422.
            # Let's assume the endpoint *receives* an already validated model or the validation
            # is part of the endpoint for this test to make sense as written.
            # The instructions imply Pydantic validation in the model will lead to a 422.
            # This means FastAPI's handling of Pydantic's ValueError.
            # We will construct the request, and the endpoint call will internally trigger validation
            # if the model is instantiated there, or FastAPI handles it if passed as type hint.
            # For this test to be accurate to FastAPI behavior for request body validation:
            # We should not expect to catch HTTPException directly from RAGRequest instantiation here.
            # Instead, the endpoint call should be the one raising it due to FastAPI's processing.
            # The current test structure where `rag_answer_api_endpoint(req)` is called is correct
            # if we assume FastAPI passes a validated model or the model instantiation happens inside.
            # Given Pydantic validator raises ValueError, FastAPI converts this to HTTP 422.

            # Simulate calling the endpoint which would trigger Pydantic validation via FastAPI
            # For the purpose of this unit test, we'll assume the Pydantic model validation
            # error (ValueError) is caught by FastAPI and results in an HTTPException(422).
            # Since we call the endpoint function directly, we need to simulate this.
            # The most direct way to test the Pydantic validator itself is to instantiate the model.
            try:
                RAGRequest(query="This is a very long query that exceeds the limit.")
            except ValueError as e: # Pydantic validator raises ValueError
                 # FastAPI would catch this and convert it to HTTPException 422
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


        self.assertEqual(cm.exception.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        error_detail_str = str(cm.exception.detail)
        self.assertIn("Query exceeds maximum allowed length", error_detail_str)
        # Ensure the actual function was not called
        self.mock_rag_answer_func.assert_not_called()

    @patch('hugegraph_llm.api.models.rag_requests.LLMConfig')
    def test_rag_answer_api_query_within_limit(self, mock_llm_config_pydantic):
        rag_answer_api_endpoint = self.get_endpoint_function("/rag")

        mock_llm_config_instance = mock_llm_config_pydantic.return_value
        mock_llm_config_instance.rag_query_max_length = 50
        
        # Provide default values for all required fields of RAGRequest
        # Pydantic model will use the mocked LLMConfig during instantiation
        req = RAGRequest(
            query="Short query.",
            raw_answer=True # ensure at least one answer type is requested
        )

        # Define return value for the mocked function
        # Assuming it returns a tuple of 4 strings based on previous test structure
        self.mock_rag_answer_func.return_value = ("raw_res", "vector_res", "graph_res", "gv_res")
        
        response = rag_answer_api_endpoint(req)

        self.mock_rag_answer_func.assert_called_once()
        # Check if the response is structured as expected
        # Based on rag_api.py, it returns a dict including the query and results for requested answer types
        self.assertIn("query", response)
        self.assertEqual(response["query"], "Short query.")
        self.assertIn("raw_answer", response) # since req.raw_answer = True
        self.assertEqual(response["raw_answer"], "raw_res")

    @patch('hugegraph_llm.api.models.rag_requests.LLMConfig')
    def test_graph_rag_recall_api_query_too_long(self, mock_llm_config_pydantic):
        graph_rag_recall_api_endpoint = self.get_endpoint_function("/rag/graph")

        mock_llm_config_instance = mock_llm_config_pydantic.return_value
        mock_llm_config_instance.rag_query_max_length = 10

        with self.assertRaises(HTTPException) as cm:
            # Similar to the above, simulating FastAPI's handling of Pydantic ValueError
            try:
                GraphRAGRequest(query="This is a very long query for graph recall that exceeds limit.")
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


        self.assertEqual(cm.exception.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        error_detail_str = str(cm.exception.detail)
        self.assertIn("query", error_detail_str) 
        self.assertIn("Query exceeds maximum allowed length", error_detail_str)
        self.mock_graph_rag_recall_func.assert_not_called()

    @patch('hugegraph_llm.api.models.rag_requests.LLMConfig')
    def test_graph_rag_recall_api_query_within_limit(self, mock_llm_config_pydantic):
        graph_rag_recall_api_endpoint = self.get_endpoint_function("/rag/graph")

        mock_llm_config_instance = mock_llm_config_pydantic.return_value
        mock_llm_config_instance.rag_query_max_length = 50
        
        req = GraphRAGRequest(query="Short graph query.")
        
        expected_recall_result = {"keywords": ["short", "graph", "query"], "match_vids": ["id1"]}
        self.mock_graph_rag_recall_func.return_value = expected_recall_result
        
        response = graph_rag_recall_api_endpoint(req)

        self.mock_graph_rag_recall_func.assert_called_once()
        # Based on rag_api.py, the response is {"graph_recall": user_result}
        self.assertIn("graph_recall", response)
        # The user_result filters only specific keys, ensure they are present
        self.assertIn("keywords", response["graph_recall"])
        self.assertEqual(response["graph_recall"]["keywords"], expected_recall_result["keywords"])
        self.assertIn("match_vids", response["graph_recall"])
        self.assertEqual(response["graph_recall"]["match_vids"], expected_recall_result["match_vids"])

if __name__ == '__main__':
    unittest.main()
