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

"""Tests for parse_json_response shared utility."""

import pytest

from hugegraph_llm.benchmark.llm_judge.judge_utils import parse_json_response

pytestmark = pytest.mark.unit


def test_parsejsonresponsedirect_simple_json():
    result = parse_json_response('{"score": 0.8}')
    assert result == {'score': 0.8}


def test_parsejsonresponsedirect_nested_json():
    text = '{"verdicts": [{"verdict": "yes"}, {"verdict": "no"}]}'
    result = parse_json_response(text)
    assert result is not None
    assert len(result['verdicts']) == 2


def test_parsejsonresponsedirect_with_whitespace():
    result = parse_json_response('  \n  {"key": "value"}  \n  ')
    assert result == {'key': 'value'}


def test_parsejsonresponsemarkdown_json_code_block():
    text = 'Here is the result:\n```json\n{"score": 0.9}\n```\nDone.'
    result = parse_json_response(text)
    assert result == {'score': 0.9}


def test_parsejsonresponsemarkdown_plain_code_block():
    text = '```\n{"answer": "yes"}\n```'
    result = parse_json_response(text)
    assert result == {'answer': 'yes'}


def test_parsejsonresponsemarkdown_multiple_code_blocks():
    text = '```\nsome text\n```\n```json\n{"found": true}\n```'
    result = parse_json_response(text)
    assert result == {'found': True}


def test_parsejsonresponseregex_json_embedded_in_text():
    text = 'The analysis shows {"verdict": "yes", "reason": "correct"} as expected.'
    result = parse_json_response(text)
    assert result is not None
    assert result['verdict'] == 'yes'


def test_parsejsonresponseregex_nested_braces():
    text = 'Result: {"data": {"nested": true}} end.'
    result = parse_json_response(text)
    assert result is not None
    assert result['data']['nested'] is True


def test_parsejsonresponsefailure_empty_string():
    result = parse_json_response('')
    assert result is None


def test_parsejsonresponsefailure_plain_text_no_json():
    result = parse_json_response('This is just plain text with no JSON at all.')
    assert result is None


def test_parsejsonresponsefailure_malformed_json():
    result = parse_json_response('{invalid json content}')
    assert result is None


def test_parsejsonresponseimportable_import_from_package():
    from hugegraph_llm.benchmark.llm_judge import parse_json_response as pjr

    assert pjr is parse_json_response
