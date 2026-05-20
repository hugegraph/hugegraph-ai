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

import unittest
from unittest.mock import Mock

import requests
from pyhugegraph.utils.util import ResponseValidation


class TestResponseValidation(unittest.TestCase):
    def _mock_error_response(self, body, text):
        response = Mock(spec=requests.Response)
        response.status_code = 400
        response.text = text
        response.content = response.text.encode("utf-8")
        response.json.return_value = body
        response.request = Mock()
        response.request.body = "g.V2()"
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Client Error")
        return response

    def test_numeric_status_body_raises_server_exception_with_message(self):
        response = self._mock_error_response(
            {"status": 400, "message": "bad gremlin"},
            '{"status":400,"message":"bad gremlin"}',
        )
        validator = ResponseValidation()

        with self.assertRaisesRegex(Exception, "Server Exception: bad gremlin"):
            validator(response, "POST", "/gremlin")

    def test_non_dict_json_body_raises_server_exception_with_response_text(self):
        response = self._mock_error_response(["bad gremlin"], "bad gremlin")
        validator = ResponseValidation()

        with self.assertRaisesRegex(Exception, "Server Exception: bad gremlin"):
            validator(response, "POST", "/gremlin")


if __name__ == "__main__":
    unittest.main()
