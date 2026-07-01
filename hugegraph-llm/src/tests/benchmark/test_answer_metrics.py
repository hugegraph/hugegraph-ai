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

"""Tests for answer metrics: TokenF1, ExactMatch, RougeL."""

import pytest

from hugegraph_llm.benchmark.metrics.answer.exact_match import ExactMatch
from hugegraph_llm.benchmark.metrics.answer.rouge_l import RougeL
from hugegraph_llm.benchmark.metrics.answer.token_f1 import TokenF1

pytestmark = pytest.mark.unit


def test_tokenf1_perfect_match():
    metric = TokenF1()
    result = metric.calculate('the cat sat', 'the cat sat')
    assert result['token_f1'] == 1.0
    assert result['token_precision'] == 1.0
    assert result['token_recall'] == 1.0


def test_tokenf1_complete_mismatch():
    metric = TokenF1()
    result = metric.calculate('hello world', 'foo bar baz')
    assert result['token_f1'] == 0.0


def test_tokenf1_partial_match():
    metric = TokenF1()
    result = metric.calculate('big cat', 'big dog')
    assert result['token_f1'] == 0.5


def test_tokenf1_multiple_gold_answers_takes_max():
    metric = TokenF1()
    pred = 'paris'
    refs = ['london', 'paris france']
    result = metric.calculate(pred, refs)
    assert result['token_f1'] > 0.0


def test_tokenf1_empty_prediction():
    metric = TokenF1()
    result = metric.calculate('', 'some answer')
    assert result['token_f1'] == 0.0


def test_tokenf1_empty_reference():
    metric = TokenF1()
    result = metric.calculate('some prediction', '')
    assert result['token_f1'] == 0.0


def test_tokenf1_both_empty():
    metric = TokenF1()
    result = metric.calculate('', '')
    assert result['token_f1'] == 1.0


def test_tokenf1_chinese_tokenization():
    metric = TokenF1()
    # Chinese text should be segmented with jieba.
    pred = '北京是中国的首都'
    ref = '中国首都是北京'
    result = metric.calculate(pred, ref, language='zh')
    assert result['token_f1'] > 0.0
    assert 0.0 <= result['token_f1'] <= 1.0


def test_exactmatch_exact_same_string():
    metric = ExactMatch()
    result = metric.calculate('Paris', 'Paris')
    assert result['exact_match'] == 1.0


def test_exactmatch_case_insensitive():
    metric = ExactMatch()
    result = metric.calculate('PARIS', 'paris')
    assert result['exact_match'] == 1.0


def test_exactmatch_punctuation_ignored():
    metric = ExactMatch()
    result = metric.calculate('Paris!', 'Paris')
    assert result['exact_match'] == 1.0


def test_exactmatch_articles_removed_en():
    metric = ExactMatch()
    result = metric.calculate('the Paris', 'Paris', language='en')
    assert result['exact_match'] == 1.0


def test_exactmatch_whitespace_normalized():
    metric = ExactMatch()
    result = metric.calculate('  Paris  ', 'Paris')
    assert result['exact_match'] == 1.0


def test_exactmatch_no_match():
    metric = ExactMatch()
    result = metric.calculate('London', 'Paris')
    assert result['exact_match'] == 0.0


def test_exactmatch_multiple_gold_any_matches():
    metric = ExactMatch()
    result = metric.calculate('Paris', ['London', 'Paris'])
    assert result['exact_match'] == 1.0


def test_exactmatch_multiple_gold_none_matches():
    metric = ExactMatch()
    result = metric.calculate('Berlin', ['London', 'Paris'])
    assert result['exact_match'] == 0.0


def test_exactmatch_empty_inputs():
    metric = ExactMatch()
    result = metric.calculate('', '')
    assert result['exact_match'] == 1.0


def test_rougel_perfect_match():
    metric = RougeL()
    result = metric.calculate('the cat sat on mat', 'the cat sat on mat')
    assert result['rouge_l_f1'] == 1.0
    assert result['rouge_l_precision'] == 1.0
    assert result['rouge_l_recall'] == 1.0


def test_rougel_complete_mismatch():
    metric = RougeL()
    result = metric.calculate('hello world', 'foo bar')
    assert result['rouge_l_f1'] == 0.0


def test_rougel_partial_match():
    metric = RougeL()
    result = metric.calculate('big cat sat', 'big dog sat')
    assert abs(result['rouge_l_f1'] - 2 / 3) < 0.01


def test_rougel_empty_prediction():
    metric = RougeL()
    result = metric.calculate('', 'some reference')
    assert result['rouge_l_f1'] == 0.0


def test_rougel_empty_reference():
    metric = RougeL()
    result = metric.calculate('some prediction', '')
    assert result['rouge_l_f1'] == 0.0


def test_rougel_both_empty():
    metric = RougeL()
    result = metric.calculate('', '')
    assert result['rouge_l_f1'] == 1.0


def test_rougel_score_range():
    metric = RougeL()
    result = metric.calculate('a b c d e', 'c d e f g')
    assert 0.0 <= result['rouge_l_f1'] <= 1.0
    assert 0.0 <= result['rouge_l_precision'] <= 1.0
    assert 0.0 <= result['rouge_l_recall'] <= 1.0


# --- Alignment tests: verify preprocessing matches open-source frameworks ---


def test_normalize_does_not_remove_conjunction_and():
    """'and' is a conjunction, not an article.

    Aligns with SQuAD / HippoRAG 2 normalize_answer which removes only
    a/an/the. Our earlier impl wrongly stripped 'and' too.
    """
    metric = ExactMatch()
    # 'cat and dog' → 'cat and dog' (and retained); must NOT equal 'cat dog'.
    result = metric.calculate('cat and dog', 'cat dog', language='en')
    assert result['exact_match'] == 0.0


def test_tokenf1_no_porter_stemming():
    """No stemming in token F1 — aligns with HippoRAG 2 QAF1Score.

    HippoRAG 2 tokenizes via normalize_answer().split() with no stemmer.
    Earlier impl applied Porter stemming, inflating scores for inflected forms.
    """
    metric = TokenF1()
    # 'running' and 'run' are distinct tokens without a stemmer.
    result = metric.calculate('running', 'run')
    assert result['token_f1'] == 0.0


def test_rougel_aligns_with_official_package():
    """English ROUGE-L must equal the rouge_score package (GraphRAG-Bench).

    GraphRAG-Bench uses rouge_score.RougeScorer(['rougeL'], use_stemmer=True);
    our EN path delegates to it, so results must match bit-for-bit.
    """
    from rouge_score import rouge_scorer

    metric = RougeL()
    scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
    cases = [
        ('the cat sat', 'a cat sat'),
        ('big cat sat', 'big dog sat'),
        ('hello world', 'foo bar'),
        ('a b c d e', 'c d e f g'),
    ]
    for pred, ref in cases:
        ours = metric.calculate(pred, ref)['rouge_l_f1']
        theirs = round(scorer.score(ref, pred)['rougeL'].fmeasure, 4)
        assert ours == theirs, f"{pred!r} vs {ref!r}: ours={ours} pkg={theirs}"


def test_rougel_multiple_gold_takes_max():
    metric = RougeL()
    result = metric.calculate('paris', ['london', 'paris france'])
    assert result['rouge_l_f1'] > 0.0


def test_rougel_chinese_via_jieba_lcs():
    """Chinese ROUGE-L uses jieba + LCS (rouge_score drops non-ASCII)."""
    metric = RougeL()
    result = metric.calculate('北京是中国的首都', '中国首都是北京', language='zh')
    assert 0.0 <= result['rouge_l_f1'] <= 1.0


def test_normalize_answer_aligns_with_hipporag_sqad_standard():
    """EN normalize_answer must equal HippoRAG 2's verbatim (standard SQuAD).

    HippoRAG 2 eval_utils.normalize_answer:
        lowercase → remove punctuation → remove a/an/the → collapse whitespace.
    Locking this prevents regressions (e.g. re-adding 'and' removal or extra
    comma stripping that diverge from the open-source standard).
    """
    import re
    import string

    def sqad_normalize(s):  # verbatim HippoRAG 2 reference
        def remove_articles(text):
            return re.sub(r"\b(a|an|the)\b", " ", text)

        def white_space_fix(text):
            return " ".join(text.split())

        def remove_punc(text):
            exclude = set(string.punctuation)
            return "".join(ch for ch in text if ch not in exclude)

        def lower(text):
            return text.lower()

        return white_space_fix(remove_articles(remove_punc(lower(s))))

    from hugegraph_llm.benchmark.utils.normalize import normalize_answer

    cases = [
        "The quick brown fox",
        "A, B, and C",
        "It's 100% correct!",
        "New York City",
        "the United States of America",
        "",
        "UPPERCASE Text",
    ]
    for c in cases:
        assert normalize_answer(c, "en") == sqad_normalize(c), f"diverge on {c!r}"
