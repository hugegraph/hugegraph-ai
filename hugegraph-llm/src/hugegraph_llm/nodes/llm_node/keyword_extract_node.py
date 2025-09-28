#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from typing import Dict, Any
from PyCGraph import CStatus

from hugegraph_llm.nodes.base_node import BaseNode
from hugegraph_llm.operators.llm_op.keyword_extract import KeywordExtract
from hugegraph_llm.utils.log import log


class KeywordExtractNode(BaseNode):
    operator: KeywordExtract

    """
    Keyword extraction node, responsible for extracting keywords from query text.
    """

    def __init__(self):
        super().__init__()
        self.operator = None

    def node_init(self):
        """
        Initialize the keyword extraction operator.
        """
        try:
            max_keywords = (
                self.wk_input.max_keywords
                if self.wk_input.max_keywords is not None
                else 5
            )
            language = (
                self.wk_input.language
                if self.wk_input.language is not None
                else "english"
            )
            extract_template = self.wk_input.keywords_extract_prompt

            self.operator = KeywordExtract(
                # Check if self.wk_input.texts is a list[str], if not, convert to list[str]
                text=self.wk_input.query,
                max_keywords=max_keywords,
                language=language,
                extract_template=extract_template,
            )
            return super().node_init()
        except Exception as e:
            log.error(f"Failed to initialize KeywordExtractNode: {e}")
            return CStatus(-1, f"KeywordExtractNode initialization failed: {e}")

    def operator_schedule(self, data_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the keyword extraction operation.
        """
        try:
            # Get the query text from input
            print("debugdd")
            # Perform keyword extraction
            result = self.operator.run(data_json)

            log.info(f"Extracted keywords: {result.get('keywords', [])}")

            return result

        except Exception as e:
            log.error(f"Keyword extraction failed: {e}")
            return data_json
