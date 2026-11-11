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

"""Literal file selectors must not expand to sibling documents."""

import pytest

from ontogeny.core.models import DocumentCfg
from ontogeny.documents.corpus import scan


@pytest.mark.parametrize("directory", ["", "nested"])
def test_file_selector_only_returns_selected_file(tmp_path, directory):
    folder = tmp_path / directory
    folder.mkdir(exist_ok=True)
    target = folder / "selected.md"
    target.write_text("selected")
    (folder / "sibling.md").write_text("sibling")
    docs = scan(tmp_path, DocumentCfg(), target.relative_to(tmp_path).as_posix(), store_name="docs")
    assert [doc.path for doc in docs] == [target]
    assert docs[0].rel == "selected.md"


def test_file_selector_respects_excludes(tmp_path):
    (tmp_path / "selected.md").write_text("selected")
    docs = scan(tmp_path, DocumentCfg(exclude=["selected.md"]), "selected.md", store_name="docs")
    assert docs == []


def test_directory_selector_keeps_all_matching_files(tmp_path):
    folder = tmp_path / "nested"
    folder.mkdir()
    for name in ["a.md", "b.md"]:
        (folder / name).write_text(name)
    assert [doc.rel for doc in scan(tmp_path, DocumentCfg(), "nested", store_name="docs")] == ["a.md", "b.md"]
