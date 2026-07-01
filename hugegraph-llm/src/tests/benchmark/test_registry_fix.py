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

"""Tests for MetricRegistry module-level dict fix."""

import pytest

from hugegraph_llm.benchmark.metrics.base import BaseMetric
from hugegraph_llm.benchmark.metrics.registry import _METRIC_REGISTRY, MetricRegistry

pytestmark = pytest.mark.unit


def test_metricregistrymodulelevel_module_level_registry_exists():
    assert isinstance(_METRIC_REGISTRY, dict)


def test_metricregistrymodulelevel_registry_not_class_variable():
    assert not hasattr(MetricRegistry, '_registry')


def test_metricregistrymodulelevel_registered_metrics_in_module_dict():
    assert 'entity_f1' in _METRIC_REGISTRY


def test_metricregistryoperations_get_known_metric():
    cls = MetricRegistry.get('entity_f1')
    assert cls is not None


def test_metricregistryoperations_get_unknown_returns_none():
    assert MetricRegistry.get('nonexistent_xyz_abc') is None


def test_metricregistryoperations_create_returns_instance():
    instance = MetricRegistry.create('entity_f1')
    assert isinstance(instance, BaseMetric)


def test_metricregistryoperations_create_unknown_raises_key_error():
    with pytest.raises(KeyError, match='Unknown metric'):
        MetricRegistry.create('nonexistent_xyz_abc')


def test_metricregistryoperations_list_metrics_returns_sorted():
    names = MetricRegistry.list_metrics()
    assert isinstance(names, list)
    assert names == sorted(names)
    assert len(names) > 0


def test_metricregistryoperations_list_by_category():
    entity_metrics = MetricRegistry.list_by_category('entity')
    assert 'entity_f1' in entity_metrics


def test_metricregistryoperations_register_requires_name():

    class NoName(BaseMetric):
        name = ''

        def calculate(self, prediction, reference, **kwargs):
            return {}

    with pytest.raises(ValueError, match="must set 'name'"):
        MetricRegistry.register(NoName)


def test_metricregistryoperations_duplicate_register_overwrites():
    """Registering the same name twice should overwrite."""

    class V1(BaseMetric):
        name = '_test_dup_metric'

        def calculate(self, prediction, reference, **kwargs):
            return {'v': 1.0}

    class V2(BaseMetric):
        name = '_test_dup_metric'

        def calculate(self, prediction, reference, **kwargs):
            return {'v': 2.0}

    MetricRegistry.register(V1)
    assert MetricRegistry.create('_test_dup_metric').calculate([], []) == {'v': 1.0}
    MetricRegistry.register(V2)
    assert MetricRegistry.create('_test_dup_metric').calculate([], []) == {'v': 2.0}
    del _METRIC_REGISTRY['_test_dup_metric']
