# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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

    @patch('hugegraph_llm.api.rag_api.log')
    @patch('hugegraph_llm.api.rag_api.LLMConfig')
    def test_rag_answer_api_query_too_long(self, mock_llm_config, mock_log):
        rag_answer_api_endpoint = self.get_endpoint_function("/rag")

        mock_llm_config_instance = mock_llm_config.return_value
        mock_llm_config_instance.rag_query_max_length = 10

        req = RAGRequest(query="This is a very long query that exceeds the limit.")

        with self.assertRaises(HTTPException) as cm:
            rag_answer_api_endpoint(req)

        self.assertEqual(cm.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            cm.exception.detail,
            "Query is too long. Maximum allowed length is 10 characters.",
        )
        mock_log.warning.assert_called_once()
        # Ensure the actual function was not called
        self.mock_rag_answer_func.assert_not_called()

    @patch('hugegraph_llm.api.rag_api.log') # Mock log even for success cases if there are internal logs
    @patch('hugegraph_llm.api.rag_api.LLMConfig')
    def test_rag_answer_api_query_within_limit(self, mock_llm_config, mock_log):
        rag_answer_api_endpoint = self.get_endpoint_function("/rag")

        mock_llm_config_instance = mock_llm_config.return_value
        mock_llm_config_instance.rag_query_max_length = 50
        
        # Provide default values for all required fields of RAGRequest
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
        mock_log.warning.assert_not_called() # No warning for valid query

    @patch('hugegraph_llm.api.rag_api.log')
    @patch('hugegraph_llm.api.rag_api.LLMConfig')
    def test_graph_rag_recall_api_query_too_long(self, mock_llm_config, mock_log):
        graph_rag_recall_api_endpoint = self.get_endpoint_function("/rag/graph")

        mock_llm_config_instance = mock_llm_config.return_value
        mock_llm_config_instance.rag_query_max_length = 10

        req = GraphRAGRequest(query="This is a very long query for graph recall that exceeds limit.")

        with self.assertRaises(HTTPException) as cm:
            graph_rag_recall_api_endpoint(req)

        self.assertEqual(cm.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            cm.exception.detail,
            "Query is too long. Maximum allowed length is 10 characters.",
        )
        mock_log.warning.assert_called_once()
        self.mock_graph_rag_recall_func.assert_not_called()

    @patch('hugegraph_llm.api.rag_api.log')
    @patch('hugegraph_llm.api.rag_api.LLMConfig')
    def test_graph_rag_recall_api_query_within_limit(self, mock_llm_config, mock_log):
        graph_rag_recall_api_endpoint = self.get_endpoint_function("/rag/graph")

        mock_llm_config_instance = mock_llm_config.return_value
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
        mock_log.warning.assert_not_called()

if __name__ == '__main__':
    unittest.main()
