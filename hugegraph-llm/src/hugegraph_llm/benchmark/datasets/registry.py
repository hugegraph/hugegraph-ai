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

"""Registry for public benchmark datasets and their raw-file layout."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_RAW_DATA_DIR = Path(__file__).resolve().parents[4] / "benchmark_data" / "raw"


@dataclass(frozen=True)
class DownloadFile:
    """A file or archive that can be downloaded into the raw dataset cache."""

    url: str
    path: str
    kind: str = "file"  # "file" or "zip"
    strip_components: int = 0


@dataclass(frozen=True)
class DatasetSpec:
    """Metadata needed to validate and optionally download a public dataset."""

    name: str
    title: str
    expected_files: List[str]
    source_url: str
    downloadable: bool = False
    download_files: List[DownloadFile] = field(default_factory=list)
    postprocess: Optional[str] = None
    notes: str = ""


def _hf_url(repo: str, path: str) -> str:
    return f"https://huggingface.co/datasets/{repo}/resolve/main/{path}?download=true"


DATASET_SPECS: Dict[str, DatasetSpec] = {
    "hotpotqa": DatasetSpec(
        name="hotpotqa",
        title="HotpotQA dev distractor",
        expected_files=[
            "hotpotqa/hotpotqa.json",
            "hotpotqa/hotpotqa_corpus.json",
        ],
        source_url="https://hotpotqa.github.io/",
        downloadable=True,
        download_files=[
            DownloadFile(
                url="http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json",
                path="hotpotqa/hotpotqa.json",
            )
        ],
        postprocess="hotpotqa_corpus",
        notes="Downloads the official dev-distractor split and derives hotpotqa_corpus.json from its context field.",
    ),
    "2wikimultihopqa": DatasetSpec(
        name="2wikimultihopqa",
        title="2WikiMultiHopQA",
        expected_files=[
            "2wikimultihopqa/2wikimultihopqa.json",
            "2wikimultihopqa/2wikimultihopqa_corpus.json",
        ],
        source_url="https://github.com/Alab-NII/2wikimultihop",
        notes=(
            "Automatic download is not enabled because public mirrors expose multiple schemas. "
            "Place converted JSON files in the expected paths or use --data-root."
        ),
    ),
    "musique": DatasetSpec(
        name="musique",
        title="MuSiQue",
        expected_files=[
            "musique/musique.json",
        ],
        source_url="https://github.com/stonybrooknlp/musique",
        notes=(
            "Automatic download is not enabled because the official release uses scripts and multiple splits. "
            "Place converted JSON files in the expected paths or use --data-root."
        ),
    ),
    "anonyrag-chs": DatasetSpec(
        name="anonyrag-chs",
        title="AnonyRAG Chinese",
        expected_files=[
            "anonyrag/annoyrag_chs_qa.parquet",
        ],
        source_url="https://huggingface.co/datasets/Youtu-Graph/AnonyRAG",
        downloadable=True,
        download_files=[
            DownloadFile(
                url=_hf_url("Youtu-Graph/AnonyRAG", "annoyrag_chs_qa.parquet"),
                path="anonyrag/annoyrag_chs_qa.parquet",
            ),
            DownloadFile(
                url=_hf_url("Youtu-Graph/AnonyRAG", "annoyrag_chs_text_chunks.parquet"),
                path="anonyrag/annoyrag_chs_text_chunks.parquet",
            ),
        ],
    ),
    "anonyrag-eng": DatasetSpec(
        name="anonyrag-eng",
        title="AnonyRAG English",
        expected_files=[
            "anonyrag/annoyrag_eng_qa.parquet",
        ],
        source_url="https://huggingface.co/datasets/Youtu-Graph/AnonyRAG",
        downloadable=True,
        download_files=[
            DownloadFile(
                url=_hf_url("Youtu-Graph/AnonyRAG", "annoyrag_eng_qa.parquet"),
                path="anonyrag/annoyrag_eng_qa.parquet",
            ),
            DownloadFile(
                url=_hf_url("Youtu-Graph/AnonyRAG", "annoyrag_eng_text_chunks.parquet"),
                path="anonyrag/annoyrag_eng_text_chunks.parquet",
            ),
        ],
    ),
    "graphrag-bench-medical": DatasetSpec(
        name="graphrag-bench-medical",
        title="GraphRAG-Bench Medical",
        expected_files=[
            "graphrag-bench/Questions/medical_questions.json",
            "graphrag-bench/Corpus/medical.json",
        ],
        source_url="https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench",
        downloadable=True,
        download_files=[
            DownloadFile(
                url=_hf_url("GraphRAG-Bench/GraphRAG-Bench", "Datasets/Questions/medical_questions.json"),
                path="graphrag-bench/Questions/medical_questions.json",
            ),
            DownloadFile(
                url=_hf_url("GraphRAG-Bench/GraphRAG-Bench", "Datasets/Corpus/medical.json"),
                path="graphrag-bench/Corpus/medical.json",
            ),
        ],
    ),
    "graphrag-bench-novel": DatasetSpec(
        name="graphrag-bench-novel",
        title="GraphRAG-Bench Novel",
        expected_files=[
            "graphrag-bench/Questions/novel_questions.json",
            "graphrag-bench/Corpus/novel.json",
        ],
        source_url="https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench",
        downloadable=True,
        download_files=[
            DownloadFile(
                url=_hf_url("GraphRAG-Bench/GraphRAG-Bench", "Datasets/Questions/novel_questions.json"),
                path="graphrag-bench/Questions/novel_questions.json",
            ),
            DownloadFile(
                url=_hf_url("GraphRAG-Bench/GraphRAG-Bench", "Datasets/Corpus/novel.json"),
                path="graphrag-bench/Corpus/novel.json",
            ),
        ],
    ),
    "text2kgbench": DatasetSpec(
        name="text2kgbench",
        title="Text2KGBench",
        expected_files=[
            "text2kgbench/wikidata_tekgen/ontologies/1_movie_ontology.json",
            "text2kgbench/wikidata_tekgen/test/ont_1_movie_test.jsonl",
            "text2kgbench/wikidata_tekgen/ground_truth/ont_1_movie_ground_truth.jsonl",
        ],
        source_url="https://github.com/cenguix/Text2KGBench",
        downloadable=True,
        download_files=[
            DownloadFile(
                url="https://github.com/cenguix/Text2KGBench/archive/refs/heads/main.zip",
                path="text2kgbench",
                kind="zip",
                strip_components=1,
            )
        ],
    ),
}


DATASET_ALIASES: Dict[str, List[str]] = {
    "all": list(DATASET_SPECS),
    "anonyrag": ["anonyrag-chs", "anonyrag-eng"],
    "graphrag-bench": ["graphrag-bench-medical", "graphrag-bench-novel"],
}


def expand_dataset_names(dataset: str) -> List[str]:
    """Expand aggregate dataset names to concrete registry names."""
    if dataset in DATASET_ALIASES:
        return DATASET_ALIASES[dataset]
    return [dataset]


def get_dataset_spec(dataset: str) -> DatasetSpec:
    """Return a dataset spec or raise a helpful KeyError."""
    if dataset not in DATASET_SPECS:
        supported = ", ".join(sorted(DATASET_SPECS))
        raise KeyError(f"Unknown dataset {dataset!r}. Supported datasets: {supported}")
    return DATASET_SPECS[dataset]
