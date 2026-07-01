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

"""Tests for retrieval metrics: RecallAtK, HitAtK, MRR."""

import pytest

from hugegraph_llm.benchmark.metrics.retrieval.hit_at_k import HitAtK
from hugegraph_llm.benchmark.metrics.retrieval.mrr import MRR
from hugegraph_llm.benchmark.metrics.retrieval.recall_at_k import RecallAtK

pytestmark = pytest.mark.unit


def test_recallatk_full_recall():
    metric = RecallAtK()
    pred = ['doc1', 'doc2', 'doc3']
    ref = ['doc1', 'doc2']
    result = metric.calculate(pred, ref, k_list=[1, 5])
    assert result['recall@1'] == 0.5
    assert result['recall@5'] == 1.0


def test_recallatk_zero_recall():
    metric = RecallAtK()
    pred = ['doc_a', 'doc_b']
    ref = ['doc_x', 'doc_y']
    result = metric.calculate(pred, ref, k_list=[1, 5])
    assert result['recall@1'] == 0.0
    assert result['recall@5'] == 0.0


def test_recallatk_partial_recall():
    metric = RecallAtK()
    pred = ['doc1', 'doc_x', 'doc2', 'doc_y']
    ref = ['doc1', 'doc2', 'doc3']
    result = metric.calculate(pred, ref, k_list=[2, 4])
    assert abs(result['recall@2'] - 1 / 3) < 0.001
    assert abs(result['recall@4'] - 2 / 3) < 0.001


def test_recallatk_default_k_list():
    metric = RecallAtK()
    # Default k_list should be [1, 5, 10, 20].
    pred = ['doc1']
    ref = ['doc1']
    result = metric.calculate(pred, ref)
    assert 'recall@1' in result
    assert 'recall@5' in result
    assert 'recall@10' in result
    assert 'recall@20' in result


def test_recallatk_empty_gold_returns_zero():
    metric = RecallAtK()
    pred = ['doc1', 'doc2']
    ref = []
    result = metric.calculate(pred, ref, k_list=[1, 5])
    assert result['recall@1'] == 0.0
    assert result['recall@5'] == 0.0


def test_recallatk_empty_prediction():
    metric = RecallAtK()
    pred = []
    ref = ['doc1']
    result = metric.calculate(pred, ref, k_list=[1, 5])
    assert result['recall@1'] == 0.0
    assert result['recall@5'] == 0.0


def test_hitatk_hit_any_positive():
    metric = HitAtK()
    pred = ['doc1', 'doc_x', 'doc_y']
    ref = ['doc1', 'doc2']
    result = metric.calculate(pred, ref, k_list=[1, 5])
    assert result['hit_any@1'] == 1.0
    assert result['hit_any@5'] == 1.0


def test_hitatk_hit_any_negative():
    metric = HitAtK()
    pred = ['doc_x', 'doc_y']
    ref = ['doc1', 'doc2']
    result = metric.calculate(pred, ref, k_list=[1, 5])
    assert result['hit_any@1'] == 0.0
    assert result['hit_any@5'] == 0.0


def test_hitatk_hit_all_positive():
    metric = HitAtK()
    pred = ['doc1', 'doc2', 'doc_x']
    ref = ['doc1', 'doc2']
    result = metric.calculate(pred, ref, k_list=[3])
    assert result['hit_all@3'] == 1.0


def test_hitatk_hit_all_negative():
    metric = HitAtK()
    # Only one gold doc retrieved in top-k.
    pred = ['doc1', 'doc_x', 'doc_y']
    ref = ['doc1', 'doc2']
    result = metric.calculate(pred, ref, k_list=[3])
    assert result['hit_all@3'] == 0.0


def test_hitatk_hit_any_vs_hit_all_difference():
    metric = HitAtK()
    # Demonstrate the difference between any and all.
    pred = ['doc1', 'doc_x']
    ref = ['doc1', 'doc2']
    result = metric.calculate(pred, ref, k_list=[2])
    assert result['hit_any@2'] == 1.0
    assert result['hit_all@2'] == 0.0


def test_hitatk_empty_gold():
    metric = HitAtK()
    pred = ['doc1']
    ref = []
    result = metric.calculate(pred, ref, k_list=[1])
    assert result['hit_any@1'] == 0.0
    assert result['hit_all@1'] == 0.0


def test_hitatk_empty_inputs():
    metric = HitAtK()
    result = metric.calculate([], [], k_list=[1])
    assert result['hit_any@1'] == 0.0
    assert result['hit_all@1'] == 0.0


def test_mrr_first_relevant_at_position_1():
    metric = MRR()
    pred = ['doc1', 'doc2', 'doc3']
    ref = ['doc1']
    result = metric.calculate(pred, ref)
    assert result['mrr'] == 1.0


def test_mrr_first_relevant_at_position_2():
    metric = MRR()
    pred = ['doc_x', 'doc1', 'doc3']
    ref = ['doc1']
    result = metric.calculate(pred, ref)
    assert result['mrr'] == 0.5


def test_mrr_first_relevant_at_position_3():
    metric = MRR()
    pred = ['doc_x', 'doc_y', 'doc1']
    ref = ['doc1']
    result = metric.calculate(pred, ref)
    assert abs(result['mrr'] - 1 / 3) < 0.001


def test_mrr_no_relevant_doc():
    metric = MRR()
    pred = ['doc_x', 'doc_y', 'doc_z']
    ref = ['doc1']
    result = metric.calculate(pred, ref)
    assert result['mrr'] == 0.0


def test_mrr_empty_prediction():
    metric = MRR()
    result = metric.calculate([], ['doc1'])
    assert result['mrr'] == 0.0


def test_mrr_empty_reference():
    metric = MRR()
    result = metric.calculate(['doc1'], [])
    assert result['mrr'] == 0.0


def test_mrr_both_empty():
    metric = MRR()
    result = metric.calculate([], [])
    assert result['mrr'] == 0.0
