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

"""Tests for external dataset conversion utilities."""

import json
import zipfile

import pytest

from hugegraph_llm.benchmark.datasets import download
from hugegraph_llm.benchmark.datasets.download import (
    DatasetDownloadError,
    download_dataset,
    ensure_dataset_available,
    missing_files,
)
from hugegraph_llm.benchmark.datasets.prepare_external_datasets import (
    ExternalDatasetError,
    _context_to_docs,
    _gold_docs_from_supporting,
    _load_json,
    _maybe_subset,
    _ontology_to_schema,
    _paragraphs_from_context,
    _triples_to_graph,
    prepare_hotpotqa_like,
)
from hugegraph_llm.benchmark.datasets.registry import DATASET_SPECS, expand_dataset_names

pytestmark = pytest.mark.unit


class TestMaybeSubset:
    def test_returns_full_when_n_is_none(self):
        items = [1, 2, 3, 4]
        assert _maybe_subset(items, None) == items

    def test_returns_first_n(self):
        assert _maybe_subset([1, 2, 3, 4], 2) == [1, 2]

    def test_returns_full_when_n_too_large(self):
        items = [1, 2]
        assert _maybe_subset(items, 10) == items

    def test_returns_full_when_n_zero_or_negative(self):
        items = [1, 2, 3]
        assert _maybe_subset(items, 0) == items
        assert _maybe_subset(items, -5) == items


class TestContextToDocs:
    def test_sentences_list(self):
        context = [["Title A", ["Sentence one.", "Sentence two."]]]
        docs = _context_to_docs(context)
        assert docs == ["Title A\nSentence one. Sentence two."]

    def test_single_string(self):
        context = [["Title B", "Only one sentence."]]
        docs = _context_to_docs(context)
        assert docs == ["Title B\nOnly one sentence."]

    def test_skips_malformed_items(self):
        context = [["Title C", ["ok"]], ["bad"], {"not": "list"}]
        docs = _context_to_docs(context)
        assert docs == ["Title C\nok"]


class TestGoldDocsFromSupporting:
    def test_prefers_context_doc(self):
        context = [["Earth", ["Earth is a planet."]]]
        supporting = [["Earth", 0]]
        corpus_map = {"Earth": "Fallback text."}
        assert _gold_docs_from_supporting(supporting, context, corpus_map) == ["Earth\nEarth is a planet."]

    def test_falls_back_to_corpus(self):
        context = []
        supporting = [["Mars", 0]]
        corpus_map = {"Mars": "Mars is a planet."}
        assert _gold_docs_from_supporting(supporting, context, corpus_map) == ["Mars\nMars is a planet."]

    def test_deduplicates_by_title(self):
        context = [["Earth", ["Earth is a planet."]]]
        supporting = [["Earth", 0], ["Earth", 1]]
        assert len(_gold_docs_from_supporting(supporting, context, {})) == 1


class TestParagraphsFromContext:
    def test_splits_by_newline(self):
        context = "Short.\nThis is a reasonably long paragraph that should be kept.\n\nAlso long enough."
        paragraphs = _paragraphs_from_context(context, min_len=10)
        assert paragraphs == [
            "This is a reasonably long paragraph that should be kept.",
            "Also long enough.",
        ]

    def test_fallback_to_full_context(self):
        context = "tiny"
        assert _paragraphs_from_context(context, min_len=100) == ["tiny"]


class TestLoadJson:
    def test_loads_valid_json(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        assert _load_json(path) == {"a": 1}

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(ExternalDatasetError, match="not found"):
            _load_json(tmp_path / "missing.json")

    def test_raises_on_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(ExternalDatasetError, match="Invalid JSON"):
            _load_json(path)


class TestOntologyToSchema:
    def test_basic_conversion(self):
        ontology = {
            "concepts": [
                {"qid": "Q1", "label": "film"},
                {"qid": "Q2", "label": "human"},
            ],
            "relations": [
                {"pid": "P1", "label": "director", "domain": "Q1", "range": "Q2"},
            ],
        }
        schema = _ontology_to_schema(ontology)
        assert schema["vertexlabels"] == [
            {"name": "film", "primary_keys": ["name"]},
            {"name": "human", "primary_keys": ["name"]},
        ]
        assert schema["edgelabels"] == [{"name": "director", "source_label": "film", "target_label": "human"}]


class TestTriplesToGraph:
    def test_creates_vertices_and_edges(self):
        ontology = {
            "concepts": [
                {"qid": "Q1", "label": "film"},
                {"qid": "Q2", "label": "human"},
            ],
            "relations": [
                {"pid": "P1", "label": "director", "domain": "Q1", "range": "Q2"},
            ],
        }
        triples = [{"sub": "Inception", "rel": "director", "obj": "Nolan"}]
        vertices, edges = _triples_to_graph(triples, ontology)
        assert {(v["label"], v["name"]) for v in vertices} == {("film", "Inception"), ("human", "Nolan")}
        assert edges == [{"label": "director", "outV": "Inception", "inV": "Nolan", "properties": {}}]

    def test_literal_value_as_property(self):
        ontology = {
            "concepts": [{"qid": "Q1", "label": "film"}],
            "relations": [
                {"pid": "P1", "label": "publication date", "domain": "Q1", "range": ""},
            ],
        }
        triples = [{"sub": "Inception", "rel": "publication date", "obj": "2010"}]
        vertices, edges = _triples_to_graph(triples, ontology)
        assert edges == []
        film = next(v for v in vertices if v["name"] == "Inception")
        assert film["properties"]["publication date"] == "2010"

    def test_skips_unknown_relation(self, caplog):
        ontology = {
            "concepts": [{"qid": "Q1", "label": "film"}],
            "relations": [],
        }
        triples = [{"sub": "A", "rel": "unknown", "obj": "B"}]
        with caplog.at_level("WARNING"):
            vertices, edges = _triples_to_graph(triples, ontology)
        assert not vertices and not edges
        assert "unknown relation" in caplog.text


class TestPrepareHotpotqaLike:
    def test_end_to_end_smoke(self, tmp_path):
        data_root = tmp_path / "datasets"
        dataset_dir = data_root / "hotpotqa"
        dataset_dir.mkdir(parents=True)

        qa = [
            {
                "_id": "q1",
                "question": "What is X?",
                "answer": "answer",
                "supporting_facts": [["Doc A", 0]],
                "context": [["Doc A", ["Doc A content."]], ["Doc B", ["Noise."]]],
            }
        ]
        corpus = [{"title": "Doc A", "text": "Doc A content."}]
        (dataset_dir / "hotpotqa.json").write_text(json.dumps(qa), encoding="utf-8")
        (dataset_dir / "hotpotqa_corpus.json").write_text(json.dumps(corpus), encoding="utf-8")

        output_dir = tmp_path / "out"
        output_dir.mkdir()
        prepare_hotpotqa_like("hotpotqa", subset_size=None, output_dir=output_dir, data_root=data_root)

        result = _load_json(output_dir / "hotpotqa_retrieval.json")
        assert len(result["samples"]) == 1
        sample = result["samples"][0]
        assert sample["sample_id"] == "q1"
        assert sample["gold_docs"] == ["Doc A\nDoc A content."]
        assert len(sample["retrieved_docs"]) == 2


class TestDatasetDownloadRegistry:
    def test_alias_expansion(self):
        assert expand_dataset_names("anonyrag") == ["anonyrag-chs", "anonyrag-eng"]
        assert expand_dataset_names("hotpotqa") == ["hotpotqa"]

    def test_missing_files_reports_expected_paths(self, tmp_path):
        assert missing_files(DATASET_SPECS["hotpotqa"], tmp_path) == [
            "hotpotqa/hotpotqa.json",
            "hotpotqa/hotpotqa_corpus.json",
        ]

    def test_missing_downloadable_dataset_has_actionable_message(self, tmp_path):
        with pytest.raises(DatasetDownloadError) as exc_info:
            ensure_dataset_available("hotpotqa", tmp_path, download=False)

        message = str(exc_info.value)
        assert "hotpotqa/hotpotqa.json" in message
        assert "--download" in message
        assert "--cache-dir" in message

    def test_manual_dataset_mentions_source_when_download_requested(self, tmp_path):
        with pytest.raises(DatasetDownloadError) as exc_info:
            ensure_dataset_available("musique", tmp_path, download=True)

        message = str(exc_info.value)
        assert "Automatic download is not enabled" in message
        assert "https://github.com/stonybrooknlp/musique" in message

    def test_hotpotqa_download_derives_corpus_without_network(self, tmp_path, monkeypatch):
        qa = [
            {
                "_id": "q1",
                "question": "What is X?",
                "answer": "answer",
                "supporting_facts": [["Doc A", 0]],
                "context": [["Doc A", ["Doc A content."]], ["Doc B", ["Noise."]]],
            }
        ]

        def fake_download_file(url, path, force=False):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(qa), encoding="utf-8")

        monkeypatch.setattr(download, "_download_file", fake_download_file)

        download_dataset("hotpotqa", tmp_path)

        assert (tmp_path / "hotpotqa" / "hotpotqa.json").exists()
        corpus = _load_json(tmp_path / "hotpotqa" / "hotpotqa_corpus.json")
        assert corpus == [
            {"title": "Doc A", "text": "Doc A content."},
            {"title": "Doc B", "text": "Noise."},
        ]

    def test_extract_zip_strips_top_level_directory(self, tmp_path):
        archive_path = tmp_path / "dataset.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("Text2KGBench-main/wikidata_tekgen/test/item.jsonl", "{}\n")

        target_dir = tmp_path / "raw" / "text2kgbench"
        download._extract_zip(archive_path, target_dir, strip_components=1)

        assert (target_dir / "wikidata_tekgen" / "test" / "item.jsonl").read_text(encoding="utf-8") == "{}\n"
