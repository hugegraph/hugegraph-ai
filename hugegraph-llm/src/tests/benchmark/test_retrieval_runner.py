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

"""Tests for RetrievalRunner input contract validation."""

import json

import pytest

from hugegraph_llm.benchmark.runners.retrieval_runner import RetrievalRunner

pytestmark = pytest.mark.unit


def test_retrievalrunner_fails_fast_when_ranking_metric_missing_doc_ids(tmp_path):
    data_path = tmp_path / "no_doc_ids.json"
    data_path.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "missing_doc_ids",
                        "question": "test question",
                        "retrieved_contexts": ["context"],
                        "gold_answer": "answer",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    runner = RetrievalRunner(max_workers=1)
    with pytest.raises(ValueError) as exc_info:
        runner.run(data_path=str(data_path), metrics=["recall_at_k"], k_list=[1])

    message = str(exc_info.value)
    assert "gold_doc_ids" in message
    assert "retrieved_doc_ids" in message
    assert "context_precision" in message or "context_relevancy" in message or "evidence_recall_llm" in message


def test_retrievalrunner_context_metrics_only_do_not_require_doc_ids(tmp_path):
    class _FakeLLM:
        def generate(self, prompt=None, messages=None, **kw):
            return '{"verdict": "yes"}'

    data_path = tmp_path / "context_only.json"
    data_path.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "ctx_only",
                        "question": "test question",
                        "retrieved_contexts": ["relevant context"],
                        "gold_answer": "answer",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    runner = RetrievalRunner(max_workers=1)
    result = runner.run(
        data_path=str(data_path),
        metrics=["context_precision"],
        k_list=[1],
        llm=_FakeLLM(),
    )
    assert len(result.samples) == 1
    assert result.samples[0].sample_id == "ctx_only"
    assert "context_precision" in result.samples[0].metrics


def test_retrievalrunner_rejects_non_list_doc_ids(tmp_path):
    data_path = tmp_path / "bad_doc_ids.json"
    data_path.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "bad_doc_ids",
                        "question": "test",
                        "gold_doc_ids": "doc1",
                        "retrieved_doc_ids": ["doc1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    runner = RetrievalRunner(max_workers=1)
    with pytest.raises(ValueError) as exc_info:
        runner.run(data_path=str(data_path), metrics=["recall_at_k"], k_list=[1])
    assert "must be a list" in str(exc_info.value)
