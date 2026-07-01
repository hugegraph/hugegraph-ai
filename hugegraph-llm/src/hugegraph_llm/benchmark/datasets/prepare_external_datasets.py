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

"""Convert public datasets into HugeGraph-AI benchmark input format.

Rules (aligned with the project requirement "do not invent data"):
- Only fields already present in the original dataset are used.
- For retrieval, ``gold_docs`` come from the dataset's own gold references
  (supporting facts / evidence).  ``retrieved_docs`` come from the context or
  corpus the dataset already provides, NOT from a synthetic perfect candidate.
- Ablation mode is NOT produced automatically because none of these datasets
  ships with the four answer variants required by ``AblationRunner``.
- Extraction mode is produced for Text2KGBench; ``candidate_*`` fields are left
  empty because the dataset only contains gold annotations.  Fill them with a
  real extractor / pipeline when benchmarking a system.

Supported datasets:
  hotpotqa, 2wikimultihopqa, musique,
  anonyrag-chs, anonyrag-eng,
  graphrag-bench-medical, graphrag-bench-novel,
  text2kgbench
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from hugegraph_llm.benchmark.datasets.download import DatasetDownloadError, ensure_dataset_available
from hugegraph_llm.benchmark.datasets.registry import DATASET_ALIASES, DATASET_SPECS, DEFAULT_RAW_DATA_DIR

logger = logging.getLogger(__name__)


# Raw public datasets default to a project-local cache.  The cache is ignored by
# git (hugegraph-llm/benchmark_data/) and can be populated with --download.
_DEFAULT_DATA_ROOT = DEFAULT_RAW_DATA_DIR
DATA_ROOT = Path(os.environ.get("EXTERNAL_DATASET_ROOT", _DEFAULT_DATA_ROOT))

# Default output lives outside the source tree so it stays out of the wheel
# and out of version control (see .gitignore). Override via --output-dir.
OUTPUT_DIR = Path(__file__).resolve().parents[4] / "benchmark_data" / "external"


class ExternalDatasetError(Exception):
    """Raised when a dataset cannot be loaded or converted."""


def _resolve_data_root(data_root: Optional[Path] = None) -> Path:
    root = data_root or DATA_ROOT
    return root.resolve()


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise ExternalDatasetError(f"Data file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ExternalDatasetError(f"Invalid JSON in {path}: {e}") from e


def save(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Saved: %s", path)


def _maybe_subset(items: List[Any], n: Optional[int]) -> List[Any]:
    if n is None or n <= 0 or n >= len(items):
        return items
    return items[:n]


# ---------------------------------------------------------------------------
# HotpotQA / 2WikiMultihopQA
# ---------------------------------------------------------------------------


def _load_qa_corpus(qa_file: Path, corpus_file: Path) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    qa = _load_json(qa_file)
    corpus = _load_json(corpus_file)
    if not isinstance(qa, list):
        raise ExternalDatasetError(f"Expected {qa_file} to contain a JSON list of QA items")
    if isinstance(corpus, list):
        corpus_map = {item["title"]: item["text"] for item in corpus}
    elif isinstance(corpus, dict):
        corpus_map = corpus
    else:
        raise ExternalDatasetError(f"Unsupported corpus format in {corpus_file}")
    return qa, corpus_map


def _context_to_docs(context: List[Any]) -> List[str]:
    docs = []
    for item in context:
        if isinstance(item, list) and len(item) == 2:
            title, sents = item
            text = " ".join(sents) if isinstance(sents, list) else str(sents)
            docs.append(f"{title}\n{text}")
    return docs


def _gold_docs_from_supporting(
    supporting_facts: List[Any], context: List[Any], corpus_map: Dict[str, str]
) -> List[str]:
    title_to_doc = {}
    for doc in _context_to_docs(context):
        title = doc.split("\n", 1)[0]
        title_to_doc[title] = doc

    gold = []
    seen = set()
    for fact in supporting_facts:
        if isinstance(fact, (list, tuple)) and len(fact) >= 1:
            title = fact[0]
            if title in title_to_doc and title not in seen:
                seen.add(title)
                gold.append(title_to_doc[title])
            elif title in corpus_map and title not in seen:
                seen.add(title)
                gold.append(f"{title}\n{corpus_map[title]}")
    return gold


def _qa_to_retrieval_sample(item: Dict[str, Any], corpus_map: Dict[str, str]) -> Dict[str, Any]:
    context = item.get("context", [])
    retrieved_docs = _context_to_docs(context)
    gold_docs = _gold_docs_from_supporting(item.get("supporting_facts", []), context, corpus_map)
    return {
        "sample_id": str(item.get("_id", item.get("id", "unknown"))),
        "question": item.get("question", ""),
        "gold_docs": gold_docs,
        "retrieved_docs": retrieved_docs,
        "gold_answer": str(item.get("answer", "")),
    }


def prepare_hotpotqa_like(name: str, subset_size: Optional[int], output_dir: Path, data_root: Path = DATA_ROOT) -> None:
    qa_file = data_root / name / f"{name}.json"
    corpus_file = data_root / name / f"{name}_corpus.json"
    qa, corpus_map = _load_qa_corpus(qa_file, corpus_file)
    qa = _maybe_subset(qa, subset_size)
    samples = [_qa_to_retrieval_sample(item, corpus_map) for item in qa]
    out_name = f"{name}_retrieval.json"
    save({"samples": samples}, output_dir / out_name)


# ---------------------------------------------------------------------------
# MuSiQue
# ---------------------------------------------------------------------------


def _musique_docs(item: Dict[str, Any]) -> List[str]:
    docs = []
    for p in item.get("paragraphs", []):
        title = p.get("title", "")
        text = p.get("paragraph_text", "")
        docs.append(f"{title}\n{text}")
    return docs


def _musique_gold_docs(item: Dict[str, Any]) -> List[str]:
    gold = []
    seen = set()
    for p in item.get("paragraphs", []):
        if p.get("is_supporting"):
            title = p.get("title", "")
            if title not in seen:
                seen.add(title)
                gold.append(f"{title}\n{p.get('paragraph_text', '')}")
    return gold


def prepare_musique(subset_size: Optional[int], output_dir: Path, data_root: Path = DATA_ROOT) -> None:
    qa_file = data_root / "musique" / "musique.json"
    qa = _load_json(qa_file)
    if not isinstance(qa, list):
        raise ExternalDatasetError(f"Expected {qa_file} to contain a JSON list")
    qa = _maybe_subset(qa, subset_size)
    samples = []
    for item in qa:
        samples.append(
            {
                "sample_id": str(item.get("id", "unknown")),
                "question": item.get("question", ""),
                "gold_docs": _musique_gold_docs(item),
                "retrieved_docs": _musique_docs(item),
                "gold_answer": str(item.get("answer", "")),
            }
        )
    save({"samples": samples}, output_dir / "musique_retrieval.json")


# ---------------------------------------------------------------------------
# AnonyRAG
# ---------------------------------------------------------------------------


def _load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ExternalDatasetError(f"Data file not found: {path}")
    try:
        return pd.read_parquet(path)
    except Exception as e:
        raise ExternalDatasetError(f"Failed to read parquet {path}: {e}") from e


def prepare_anonyrag(language: str, subset_size: Optional[int], output_dir: Path, data_root: Path = DATA_ROOT) -> None:
    qa_path = data_root / "anonyrag" / f"annoyrag_{language}_qa.parquet"
    qa_df = _load_parquet(qa_path)
    if subset_size:
        qa_df = qa_df.head(subset_size)

    # The original AnonyRAG dataset does not provide per-question gold chunk
    # references nor a retriever output, so both lists are left empty.
    samples = []
    for idx, row in qa_df.iterrows():
        samples.append(
            {
                "sample_id": f"anonyrag_{language}_{idx}",
                "question": str(row.get("question", "")),
                "gold_docs": [],
                "retrieved_docs": [],
                "gold_answer": str(row.get("answer", "")),
            }
        )

    save({"samples": samples}, output_dir / f"anonyrag_{language}_retrieval.json")


# ---------------------------------------------------------------------------
# GraphRAG-Bench
# ---------------------------------------------------------------------------


def _load_graphrag_bench_corpus(corpus_file: Path) -> Dict[str, str]:
    data = _load_json(corpus_file)
    if isinstance(data, list):
        return {item.get("corpus_name", f"doc_{i}"): item.get("context", "") for i, item in enumerate(data)}
    if isinstance(data, dict):
        return {data.get("corpus_name", "default"): data.get("context", "")}
    raise ExternalDatasetError(f"Unsupported corpus format in {corpus_file}")


def _paragraphs_from_context(context: str, min_len: int = 40) -> List[str]:
    paragraphs = [p.strip() for p in context.split("\n") if len(p.strip()) >= min_len]
    return paragraphs if paragraphs else [context]


def prepare_graphrag_bench(
    domain: str, subset_size: Optional[int], output_dir: Path, data_root: Path = DATA_ROOT
) -> None:
    questions_file = data_root / "graphrag-bench" / "Questions" / f"{domain}_questions.json"
    corpus_file = data_root / "graphrag-bench" / "Corpus" / f"{domain}.json"

    questions = _load_json(questions_file)
    if not isinstance(questions, list):
        raise ExternalDatasetError(f"Expected {questions_file} to contain a JSON list")
    corpus_map = _load_graphrag_bench_corpus(corpus_file)
    questions = _maybe_subset(questions, subset_size)

    samples = []
    for item in questions:
        source = item.get("source", "")
        context = corpus_map.get(source, "")
        evidence = str(item.get("evidence", "") or "").strip()
        samples.append(
            {
                "sample_id": str(item.get("id", "unknown")),
                "question": item.get("question", ""),
                "gold_docs": [evidence] if evidence else [],
                "retrieved_docs": _paragraphs_from_context(context),
                "gold_answer": str(item.get("answer", "")),
                "question_type": item.get("question_type"),
            }
        )

    out_name = f"graphrag_bench_{domain}_retrieval.json"
    save({"samples": samples}, output_dir / out_name)


# ---------------------------------------------------------------------------
# Text2KGBench
# ---------------------------------------------------------------------------


def _ontology_to_schema(ontology: Dict[str, Any]) -> Dict[str, Any]:
    vertexlabels = [{"name": c["label"], "primary_keys": ["name"]} for c in ontology.get("concepts", [])]
    qid_to_label = {c["qid"]: c["label"] for c in ontology.get("concepts", [])}
    edgelabels = []
    for r in ontology.get("relations", []):
        src = qid_to_label.get(r.get("domain", ""), "")
        dst = qid_to_label.get(r.get("range", ""), "")
        if src and dst:
            edgelabels.append({"name": r["label"], "source_label": src, "target_label": dst})
    return {"vertexlabels": vertexlabels, "edgelabels": edgelabels}


def _triples_to_graph(
    triples: List[Dict[str, Any]], ontology: Dict[str, Any]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    qid_to_label = {c["qid"]: c["label"] for c in ontology.get("concepts", [])}
    rel_to_schema = {}
    for r in ontology.get("relations", []):
        rel_to_schema[r["label"]] = {
            "source": qid_to_label.get(r.get("domain", ""), ""),
            "target": qid_to_label.get(r.get("range", ""), ""),
        }

    vertices: Dict[Tuple[str, str], Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def add_vertex(name: str, label: str) -> None:
        if not name or not label:
            return
        key = (label, name)
        if key not in vertices:
            vertices[key] = {
                "label": label,
                "name": name,
                "properties": {"name": name},
            }

    for t in triples:
        rel = t.get("rel", "")
        schema = rel_to_schema.get(rel, {})
        src_label = schema.get("source", "")
        dst_label = schema.get("target", "")
        sub = str(t.get("sub", "")).strip()
        obj = str(t.get("obj", "")).strip()
        if not sub or not obj or not rel:
            continue
        if rel not in rel_to_schema:
            logger.warning("Skipping triple with unknown relation %r", rel)
            continue
        add_vertex(sub, src_label)
        if dst_label:
            add_vertex(obj, dst_label)
            edges.append({"label": rel, "outV": sub, "inV": obj, "properties": {}})
        else:
            # Literal / date value: store as a property on the subject vertex.
            key = (src_label, sub)
            if key in vertices:
                vertices[key]["properties"][rel] = obj

    return list(vertices.values()), edges


def _iter_text2kgbench_domains(
    data_root: Path = DATA_ROOT,
) -> Iterable[Tuple[str, Path, Path, Path]]:
    """Yield (domain_slug, ontology_file, test_file, ground_truth_file)."""
    base = data_root / "text2kgbench" / "wikidata_tekgen"
    ont_dir = base / "ontologies"
    if not ont_dir.exists():
        return
    for ont_path in sorted(ont_dir.glob("*_ontology.json")):
        # e.g. "1_movie_ontology.json" -> prefix "1_movie"
        prefix = ont_path.stem.replace("_ontology", "")
        test_file = base / "test" / f"ont_{prefix}_test.jsonl"
        gt_file = base / "ground_truth" / f"ont_{prefix}_ground_truth.jsonl"
        if not test_file.exists() or not gt_file.exists():
            continue
        # domain slug, e.g. "1_movie" -> "movie"; "10_culture" -> "culture"
        domain = prefix.split("_", 1)[1] if "_" in prefix else prefix
        yield domain, ont_path, test_file, gt_file


def prepare_text2kgbench_domain(
    domain: str,
    ontology_file: Path,
    test_file: Path,
    gt_file: Path,
    subset_size: Optional[int],
    output_dir: Path,
) -> None:
    ontology = _load_json(ontology_file)

    gt_map: Dict[str, Dict[str, Any]] = {}
    with open(gt_file, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            gt_map[item["id"]] = item

    samples = []
    with open(test_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if subset_size and i >= subset_size:
                break
            test_item = json.loads(line)
            sid = test_item["id"]
            gt_item = gt_map.get(sid, {"triples": []})
            gold_vertices, gold_edges = _triples_to_graph(gt_item.get("triples", []), ontology)
            samples.append(
                {
                    "sample_id": sid,
                    "input_text": test_item.get("sent", ""),
                    "gold_vertices": gold_vertices,
                    "gold_edges": gold_edges,
                    "candidate_vertices": [],
                    "candidate_edges": [],
                }
            )

    schema = _ontology_to_schema(ontology)
    save(
        {"schema": schema, "samples": samples},
        output_dir / f"text2kgbench_{domain}_extraction.json",
    )


def prepare_text2kgbench(subset_size: Optional[int], output_dir: Path, data_root: Path = DATA_ROOT) -> None:
    for domain, ont_path, test_path, gt_path in _iter_text2kgbench_domains(data_root):
        prepare_text2kgbench_domain(domain, ont_path, test_path, gt_path, subset_size, output_dir)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert public datasets to HugeGraph-AI benchmark format without inventing data."
    )
    parser.add_argument(
        "--dataset",
        required=True,
        choices=sorted([*DATASET_SPECS, *DATASET_ALIASES]),
    )
    parser.add_argument(
        "--subset-size",
        type=int,
        default=None,
        help="Only use the first N samples for a smoke test (default: full).",
    )
    parser.add_argument(
        "--data-root",
        default=None,
        help="Root directory containing raw external datasets. Defaults to EXTERNAL_DATASET_ROOT or the project cache.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Alias for --data-root when using the project-local raw dataset cache.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download missing registered raw files into --data-root/--cache-dir before conversion.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download registered raw files even when they already exist.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="Directory to write the converted JSON files.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.data_root and args.cache_dir:
        parser.error("--data-root and --cache-dir cannot both be set")

    data_root = _resolve_data_root(Path(args.data_root or args.cache_dir) if args.data_root or args.cache_dir else None)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dispatch = {
        "hotpotqa": lambda: prepare_hotpotqa_like("hotpotqa", args.subset_size, output_dir, data_root),
        "2wikimultihopqa": lambda: prepare_hotpotqa_like("2wikimultihopqa", args.subset_size, output_dir, data_root),
        "musique": lambda: prepare_musique(args.subset_size, output_dir, data_root),
        "anonyrag-chs": lambda: prepare_anonyrag("chs", args.subset_size, output_dir, data_root),
        "anonyrag-eng": lambda: prepare_anonyrag("eng", args.subset_size, output_dir, data_root),
        "graphrag-bench-medical": lambda: prepare_graphrag_bench("medical", args.subset_size, output_dir, data_root),
        "graphrag-bench-novel": lambda: prepare_graphrag_bench("novel", args.subset_size, output_dir, data_root),
        "text2kgbench": lambda: prepare_text2kgbench(args.subset_size, output_dir, data_root),
    }

    try:
        ensure_dataset_available(args.dataset, data_root, download=args.download, force=args.force_download)

        if args.dataset == "all":
            for name, fn in dispatch.items():
                logger.info("Preparing %s...", name)
                fn()
        elif args.dataset in DATASET_ALIASES:
            for name in DATASET_ALIASES[args.dataset]:
                logger.info("Preparing %s...", name)
                dispatch[name]()
        else:
            dispatch[args.dataset]()
    except (DatasetDownloadError, ExternalDatasetError) as e:
        logger.error("%s", e)
        return 1

    logger.info("Done.")
    logger.info(
        "Note: Text2KGBench outputs have empty candidate_* fields; "
        "run a real extractor to fill them before benchmarking a system."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
