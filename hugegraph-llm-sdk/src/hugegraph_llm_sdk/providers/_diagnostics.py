# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Provider diagnostics never serialize arbitrary response or error content."""

from collections.abc import Mapping


def token_usage(usage) -> dict[str, int]:
    """Retain only numeric usage counters, excluding vendor extension fields."""
    counters = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
        if type(value) is int and value >= 0:
            counters[key] = value
    if "total_tokens" not in counters and "prompt_tokens" in counters and "completion_tokens" in counters:
        counters["total_tokens"] = counters["prompt_tokens"] + counters["completion_tokens"]
    return counters
