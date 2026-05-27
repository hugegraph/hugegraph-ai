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

"""Tests for GremlinPolicy (Milestone 3)."""

from hugegraph_mcp.gremlin_policy import GremlinDecision, GremlinPolicy, check_gremlin_read


def test_safe_query_returns_allowed():
    decision = check_gremlin_read("g.V().limit(10)")

    assert decision.allowed is True
    assert decision.classification == "safe"
    assert decision.error_type is None
    assert decision.suggestion is None


def test_unsafe_query_returns_blocked():
    decision = check_gremlin_read("g.addV('person')")

    assert decision.allowed is False
    assert decision.classification == "unsafe"
    assert decision.error_type == "UNSAFE_GREMLIN"
    assert "write" in decision.reason.lower()


def test_uncertain_query_returns_blocked():
    decision = check_gremlin_read("g.V().unknownStep()")

    assert decision.allowed is False
    assert decision.classification == "uncertain"
    assert decision.error_type == "UNSAFE_GREMLIN"
    assert "ambiguous" in decision.reason.lower() or "unknown" in decision.reason.lower()


def test_decision_is_frozen_dataclass():
    decision = check_gremlin_read("g.V().count()")

    assert isinstance(decision, GremlinDecision)
    try:
        decision.allowed = False
        assert False, "Should be frozen"
    except AttributeError:
        pass


def test_policy_class_instance():
    policy = GremlinPolicy()

    safe = policy.check_read("g.V().count()")
    assert safe.allowed is True

    unsafe = policy.check_read("g.V().drop()")
    assert unsafe.allowed is False

    uncertain = policy.check_read("g.V().map { it }")
    assert uncertain.allowed is False


def test_newly_denied_steps_as_unsafe():
    for step in ["sideEffect", "io", "call", "program"]:
        decision = check_gremlin_read(f"g.V().{step}('x')")
        assert decision.allowed is False, f"Expected blocked: {step}"
        assert decision.classification == "unsafe"


def test_accumulator_steps_as_uncertain():
    for step in ["sack", "store", "aggregate", "cap"]:
        decision = check_gremlin_read(f"g.V().{step}('x')")
        assert decision.allowed is False, f"Expected blocked: {step}"
        assert decision.classification == "uncertain"
