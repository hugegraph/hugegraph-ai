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

from typing import List, Optional

from hugegraph_llm import runtime


class CohereReranker:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def _validate(self, documents: List[str], top_n: Optional[int]) -> int:
        if not documents:
            raise ValueError("Documents list cannot be empty")
        if top_n is None:
            top_n = len(documents)
        if top_n < 0:
            raise ValueError("'top_n' should be non-negative")
        if top_n > len(documents):
            raise ValueError("'top_n' should be less than or equal to the number of documents")
        return top_n

    async def aget_rerank_lists(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[str]:
        top_n = self._validate(documents, top_n)
        if top_n == 0:
            return []

        from pyhugegraph.utils.constants import Constants

        headers = {
            "accept": Constants.HEADER_CONTENT_TYPE,
            "content-type": Constants.HEADER_CONTENT_TYPE,
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "query": query,
            "top_n": top_n,
            "documents": documents,
        }
        client = runtime.get_http_client()
        response = await client.post(self.base_url, headers=headers, json=payload)
        response.raise_for_status()
        results = response.json()["results"]
        return [documents[item["index"]] for item in results]

    def get_rerank_lists(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[str]:
        """Sync implementation using a one-shot httpx.Client.

        Self-contained on purpose: bridging into the main async loop from a sync
        caller on the loop thread (e.g. sync Gradio paths, startup checks) would
        deadlock, and offline scripts / unit tests have no main loop running at
        all. The standalone client side-steps both issues.
        """
        import httpx

        top_n = self._validate(documents, top_n)
        if top_n == 0:
            return []

        from pyhugegraph.utils.constants import Constants

        headers = {
            "accept": Constants.HEADER_CONTENT_TYPE,
            "content-type": Constants.HEADER_CONTENT_TYPE,
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "query": query,
            "top_n": top_n,
            "documents": documents,
        }
        with httpx.Client() as client:
            response = client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            results = response.json()["results"]
            return [documents[item["index"]] for item in results]
