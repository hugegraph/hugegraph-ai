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

"""Run a real vector-retrieval + LLM-answer demo on the first 20 HotpotQA samples.

This script builds a Faiss vector index over the HotpotQA context documents using
the project's configured embedding model, then for each question:
1. Embeds the question and retrieves the top-k documents by L2 distance.
2. Generates an answer with the configured chat LLM using those documents.
3. Also generates a raw answer (no context) for ablation comparison.

Outputs benchmark inputs for retrieval and ablation modes, then runs the CLI.
"""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from hugegraph_llm.config import huge_settings, llm_settings
from hugegraph_llm.indices.vector_index.faiss_vector_store import FaissVectorIndex
from hugegraph_llm.models.embeddings.init_embedding import Embeddings
from hugegraph_llm.models.llms.init_llm import get_chat_llm

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "hugegraph-llm/benchmark_data/external"
EXPERIMENT_DIR = DATA_DIR / "experiments" / f"hotpotqa_vector_demo_{time.strftime('%Y%m%d_%H%M%S')}"

# Dedicated graph name so we never overwrite the user's main "hugegraph" index.
DEMO_GRAPH_NAME = "hotpotqa20_vector_demo"
TOP_K = 5
# Large threshold so we always get TOP_K results regardless of embedding scale.
SEARCH_THRESHOLD = 1e9
BATCH_SIZE = 10


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _call_llm(messages: List[Dict[str, str]]) -> str:
    llm = get_chat_llm(llm_settings)
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            return llm.generate(messages=messages)
        except Exception as e:
            last_error = e
            logger.warning("LLM call failed (attempt %d): %s", attempt + 1, e)
            time.sleep(2**attempt)
    raise RuntimeError(f"LLM call failed after retries: {last_error}")


def _build_answer_prompt(question: str, docs: List[str]) -> List[Dict[str, str]]:
    context = "\n\n".join(docs)
    content = (
        "Answer the question using only the provided context. "
        "Keep the answer concise. If the context does not contain the answer, say \"I don't know\".\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\nAnswer:"
    )
    return [{"role": "user", "content": content}]


def _build_raw_answer_prompt(question: str) -> List[Dict[str, str]]:
    return [
        {
            "role": "user",
            "content": (
                f"Answer the question concisely based on your own knowledge.\n\nQuestion: {question}\n\nAnswer:"
            ),
        }
    ]


def _answer(question: str, docs: List[str]) -> str:
    if not docs:
        return ""
    return _call_llm(_build_answer_prompt(question, docs)).strip()


def _raw_answer(question: str) -> str:
    return _call_llm(_build_raw_answer_prompt(question)).strip()


def _load_first_n_samples(path: Path, n: int) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("samples", [])[:n]


def _save_json(data: Dict[str, Any], path: Path) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %s", path)


def _build_corpus(samples: List[Dict[str, Any]]) -> List[str]:
    """Collect unique context docs across all samples."""
    seen = set()
    corpus = []
    for s in samples:
        for doc in s.get("retrieved_docs", []):
            if doc not in seen:
                seen.add(doc)
                corpus.append(doc)
    return corpus


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _ensure_dir(EXPERIMENT_DIR)
    logger.info("Experiment directory: %s", EXPERIMENT_DIR)

    # Use a dedicated graph name to avoid clobbering the main index.
    huge_settings.graph_name = DEMO_GRAPH_NAME

    input_file = DATA_DIR / "hotpotqa_retrieval.json"
    samples = _load_first_n_samples(input_file, 20)
    logger.info("Loaded %d HotpotQA samples from %s", len(samples), input_file)

    corpus = _build_corpus(samples)
    logger.info("Corpus: %d unique docs", len(corpus))

    embedding = Embeddings().get_embedding()
    embed_dim = embedding.get_embedding_dim()
    logger.info("Embedding dim=%d model=%s", embed_dim, llm_settings.openai_embedding_model)

    # Clean any stale demo index, then build fresh.
    FaissVectorIndex.clean(DEMO_GRAPH_NAME, "chunks")
    index = FaissVectorIndex(embed_dim)
    logger.info("Embedding %d docs (batch=%d)...", len(corpus), BATCH_SIZE)
    vectors = embedding.get_texts_embeddings(corpus, batch_size=BATCH_SIZE)
    index.add(vectors, corpus)
    index.save_index_by_name(DEMO_GRAPH_NAME, "chunks")
    logger.info("Vector index built and saved (%d vectors)", index.index.ntotal)

    # Reload from disk to mimic the real query path.
    query_index = FaissVectorIndex.from_name(embed_dim, DEMO_GRAPH_NAME, "chunks")

    retrieval_samples: List[Dict[str, Any]] = []
    ablation_samples: List[Dict[str, Any]] = []

    for i, sample in enumerate(samples, 1):
        sid = sample["sample_id"]
        question = sample["question"]
        logger.info("[%d/%d] %s", i, len(samples), sid)

        qvec = embedding.get_text_embedding(question)
        retrieved = query_index.search(qvec, TOP_K, dis_threshold=SEARCH_THRESHOLD)
        retrieved_titles = [d.split("\n", 1)[0] for d in retrieved]
        logger.info("[%d/%d] Retrieved: %s", i, len(samples), retrieved_titles)

        vector_answer = _answer(question, retrieved)
        raw = _raw_answer(question)

        retrieval_samples.append(
            {
                "sample_id": sid,
                "question": question,
                "gold_docs": sample.get("gold_docs", []),
                "retrieved_docs": retrieved,
                "gold_answer": sample.get("gold_answer", ""),
            }
        )
        ablation_samples.append(
            {
                "sample_id": sid,
                "question": question,
                "gold_answer": sample.get("gold_answer", ""),
                "raw_answer": raw,
                "vector_only_answer": vector_answer,
                "vector_only_context": retrieved,
                "graph_only_answer": "",
                "graph_vector_answer": "",
            }
        )

    retrieval_file = EXPERIMENT_DIR / "hotpotqa_20_vector_retrieval.json"
    ablation_file = EXPERIMENT_DIR / "hotpotqa_20_vector_ablation.json"
    _save_json({"samples": retrieval_samples}, retrieval_file)
    _save_json({"samples": ablation_samples}, ablation_file)

    retrieval_baseline = EXPERIMENT_DIR / "hotpotqa_20_vector_retrieval_baseline.json"
    ablation_baseline = EXPERIMENT_DIR / "hotpotqa_20_vector_ablation_baseline.json"

    def run_cmd(extra: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "hugegraph_llm.benchmark", "run", *extra],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    r1 = run_cmd(
        [
            "--mode",
            "retrieval",
            "--data",
            str(retrieval_file),
            "--language",
            "en",
            "--offline",
            "--save-baseline",
            str(retrieval_baseline),
        ]
    )
    if r1.returncode != 0:
        logger.error("Retrieval benchmark failed:\n%s", r1.stderr)
        return 1
    logger.info("Retrieval baseline saved to %s", retrieval_baseline)

    r2 = run_cmd(
        [
            "--mode",
            "ablation",
            "--data",
            str(ablation_file),
            "--language",
            "en",
            "--offline",
            "--save-baseline",
            str(ablation_baseline),
        ]
    )
    if r2.returncode != 0:
        logger.error("Ablation benchmark failed:\n%s", r2.stderr)
        return 1
    logger.info("Ablation baseline saved to %s", ablation_baseline)

    summary = {
        "experiment_dir": str(EXPERIMENT_DIR),
        "sample_count": len(samples),
        "embedding_model": llm_settings.openai_embedding_model,
        "embedding_dim": embed_dim,
        "chat_model": llm_settings.openai_chat_language_model,
        "top_k": TOP_K,
        "graph_name": DEMO_GRAPH_NAME,
        "corpus_size": len(corpus),
    }
    _save_json(summary, EXPERIMENT_DIR / "summary.json")
    logger.info("Done. Summary: %s", EXPERIMENT_DIR / "summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
