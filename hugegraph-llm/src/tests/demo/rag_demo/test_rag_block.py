import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import gradio as gr # Import for type hinting, will be mocked

from hugegraph_llm.config.llm_config import LLMConfig
from hugegraph_llm.demo.rag_demo.rag_block import rag_answer, rag_answer_streaming


class TestRagBlockQueryValidation(unittest.TestCase):

    def _get_common_rag_args(self):
        return {
            "raw_answer": False,
            "vector_only_answer": False,
            "graph_only_answer": True,
            "graph_vector_answer": False,
            "graph_ratio": 0.6,
            "rerank_method": "bleu",
            "near_neighbor_first": False,
            "custom_related_information": "custom_info",
            "answer_prompt": "answer_prompt_template",
            "keywords_extract_prompt": "keywords_extract_template",
            "gremlin_tmpl_num": -1,
            "gremlin_prompt": "gremlin_prompt_template",
        }

    @patch('hugegraph_llm.demo.rag_demo.rag_block.log')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.gr.Warning')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.LLMConfig')
    def test_rag_answer_query_too_long(self, mock_llm_config, mock_gr_warning, mock_log):
        mock_llm_config_instance = mock_llm_config.return_value
        mock_llm_config_instance.rag_query_max_length = 10

        query_text = "This is a very long query that exceeds the limit."
        args = self._get_common_rag_args()
        
        result = rag_answer(text=query_text, **args)

        mock_gr_warning.assert_called_once_with(
            "Query is too long! Maximum allowed length is 10 characters."
        )
        mock_log.warning.assert_called_once()
        self.assertEqual(result, ("", "", "", ""))

    @patch('hugegraph_llm.demo.rag_demo.rag_block.RAGPipeline')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.log') # Mock log to avoid side effects if any part of RAGPipeline call logs
    @patch('hugegraph_llm.demo.rag_demo.rag_block.gr.Warning')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.LLMConfig')
    def test_rag_answer_query_within_limit(self, mock_llm_config, mock_gr_warning, mock_log, mock_rag_pipeline):
        mock_llm_config_instance = mock_llm_config.return_value
        mock_llm_config_instance.rag_query_max_length = 50

        # Configure mock RAGPipeline
        mock_pipeline_instance = mock_rag_pipeline.return_value
        mock_pipeline_instance.run = MagicMock(return_value={
            "raw_answer": "raw", 
            "vector_only_answer": "vector", 
            "graph_only_answer": "graph", 
            "graph_vector_answer": "graph_vector"
        })

        query_text = "Short query."
        args = self._get_common_rag_args()
        
        # Call the function
        result = rag_answer(text=query_text, **args)

        # Assertions
        mock_gr_warning.assert_not_called()
        # Check if RAGPipeline was instantiated and its methods called as expected
        mock_rag_pipeline.assert_called_once() 
        mock_pipeline_instance.run.assert_called_once()
        # Check returned values based on mocked RAGPipeline
        self.assertEqual(result, ("raw", "vector", "graph", "graph_vector"))


    @patch('hugegraph_llm.demo.rag_demo.rag_block.log')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.gr.Warning')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.LLMConfig')
    async def test_rag_answer_streaming_query_too_long(self, mock_llm_config, mock_gr_warning, mock_log):
        mock_llm_config_instance = mock_llm_config.return_value
        mock_llm_config_instance.rag_query_max_length = 10

        query_text = "This is a very long query that exceeds the limit for streaming."
        args = self._get_common_rag_args()

        results_collected = []
        async for res_tuple in rag_answer_streaming(text=query_text, **args):
            results_collected.append(res_tuple)
        
        mock_gr_warning.assert_called_once_with(
            "Query is too long! Maximum allowed length is 10 characters."
        )
        mock_log.warning.assert_called_once()
        self.assertEqual(len(results_collected), 1)
        self.assertEqual(results_collected[0], ("", "", "", ""))

    @patch('hugegraph_llm.demo.rag_demo.rag_block.AnswerSynthesize')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.RAGPipeline')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.log')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.gr.Warning')
    @patch('hugegraph_llm.demo.rag_demo.rag_block.LLMConfig')
    async def test_rag_answer_streaming_query_within_limit(
        self, mock_llm_config, mock_gr_warning, mock_log, mock_rag_pipeline, mock_answer_synthesize
    ):
        mock_llm_config_instance = mock_llm_config.return_value
        mock_llm_config_instance.rag_query_max_length = 50

        # Configure mock RAGPipeline
        mock_pipeline_instance = mock_rag_pipeline.return_value
        mock_pipeline_instance.run = MagicMock(return_value={"some_context_key": "some_value"}) # RAGPipeline.run is not async

        # Configure mock AnswerSynthesize
        mock_synthesize_instance = mock_answer_synthesize.return_value
        # Make run_streaming an async generator mock
        async def mock_streaming_results(*args, **kwargs):
            yield {
                "raw_answer": "s_raw", 
                "vector_only_answer": "s_vector", 
                "graph_only_answer": "s_graph", 
                "graph_vector_answer": "s_graph_vector"
            }
        mock_synthesize_instance.run_streaming = mock_streaming_results
        
        query_text = "Short query."
        args = self._get_common_rag_args()

        results_collected = []
        async for res_tuple in rag_answer_streaming(text=query_text, **args):
            results_collected.append(res_tuple)

        mock_gr_warning.assert_not_called()
        mock_rag_pipeline.assert_called_once()
        mock_pipeline_instance.run.assert_called_once()
        mock_answer_synthesize.assert_called_once()
        # mock_synthesize_instance.run_streaming.assert_called_once() # This is harder to check for async generator directly

        self.assertEqual(len(results_collected), 1)
        self.assertEqual(results_collected[0], ("s_raw", "s_vector", "s_graph", "s_graph_vector"))

if __name__ == '__main__':
    unittest.main()
