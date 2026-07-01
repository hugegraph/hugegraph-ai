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

"""Run a real-LLM retrieval + answer demo on the first 20 HotpotQA samples.

This script uses the project's configured chat LLM (e.g. deepseek-v4-flash) to:
1. Select relevant documents from the original HotpotQA context.
2. Generate an answer using only the selected documents.
3. Produce benchmark inputs for both retrieval and ablation modes.
4. Run the HugeGraph-AI benchmark CLI on those inputs.

It does NOT require a vector index or GraphRAG server, because it treats the
dataset's own context as the retrieval corpus and lets the LLM do the ranking.
This is a cheap, reproducible way to see non-trivial real-LLM numbers without
setting up embeddings.
"""

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hugegraph_llm.config import llm_settings
from hugegraph_llm.models.llms.init_llm import get_chat_llm

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "hugegraph-llm/benchmark_data/external"
EXPERIMENT_DIR = DATA_DIR / "experiments" / f"hotpotqa_llm_demo_{time.strftime('%Y%m%d_%H%M%S')}"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _call_llm(messages: List[Dict[str, str]]) -> str:
    """Call the project chat LLM with retry on transient errors."""
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


def _parse_title_list(text: str) -> List[str]:
    """Extract a list of document titles from the LLM response."""
    # Try JSON list first.
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass

    # Fall back to line parsing: look for bullets, numbers, or plain lines.
    titles = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Remove common list markers.
        line = re.sub(r"^[-*•\d]+[.)]?\s*", "", line)
        line = line.strip("\"'[]")
        if line and line.lower() not in {"none", "n/a"}:
            titles.append(line)
    return titles


def _build_select_prompt(question: str, docs: List[str]) -> List[Dict[str, str]]:
    doc_lines = []
    for i, doc in enumerate(docs, 1):
        title = doc.split("\n", 1)[0]
        body = doc[len(title) :].strip()
        doc_lines.append(f"{i}. Title: {title}\n{body}")
    content = (
        "You are a retrieval assistant. Given a question and a list of documents, "
        "return ONLY a JSON array of the titles of the documents that are relevant "
        "to answering the question. Do not include any explanation.\n\n"
        f"Question: {question}\n\n"
        "Documents:\n" + "\n\n".join(doc_lines) + "\n\n"
        "Relevant document titles as JSON array:"
    )
    return [{"role": "user", "content": content}]


def _build_answer_prompt(question: str, docs: List[str]) -> List[Dict[str, str]]:
    context = "\n\n".join(docs)
    content = (
        "Answer the question using only the provided context. "
        "Keep the answer concise. If the context does not contain the answer, say \"I don't know\".\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
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


def _select_docs(question: str, docs: List[str]) -> Tuple[List[str], List[str]]:
    """Use the LLM to pick relevant docs. Returns (selected_docs, selected_titles)."""
    if not docs:
        return [], []
    prompt = _build_select_prompt(question, docs)
    response = _call_llm(prompt)
    titles = _parse_title_list(response)
    title_to_doc = {}
    for doc in docs:
        title = doc.split("\n", 1)[0]
        title_to_doc[title] = doc
    selected = []
    for t in titles:
        # Allow fuzzy match against titles.
        if t in title_to_doc:
            selected.append(title_to_doc[t])
        else:
            for real_title, doc in title_to_doc.items():
                if t.lower() in real_title.lower() or real_title.lower() in t.lower():
                    selected.append(doc)
                    break
    # Preserve original order and deduplicate.
    seen = set()
    ordered = []
    for doc in docs:
        if doc in selected and doc not in seen:
            ordered.append(doc)
            seen.add(doc)
    return ordered, [d.split("\n", 1)[0] for d in ordered]


def _answer(question: str, docs: List[str]) -> str:
    if not docs:
        return ""
    prompt = _build_answer_prompt(question, docs)
    return _call_llm(prompt).strip()


def _raw_answer(question: str) -> str:
    prompt = _build_raw_answer_prompt(question)
    return _call_llm(prompt).strip()


def _load_first_n_samples(path: Path, n: int) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("samples", [])[:n]


def _save_json(data: Dict[str, Any], path: Path) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %s", path)


def _run_benchmark_command(mode: str, data_file: Path, baseline: Path, extra_args: List[str]) -> None:
    cmd = [
        sys.executable,
        "-m",
        "hugegraph_llm.benchmark",
        "run",
        "--mode",
        mode,
        "--data",
        str(data_file),
        "--language",
        "en",
        "--save-baseline",
        str(baseline),
    ] + extra_args
    logger.info("Running: %s", " ".join(cmd))


import subprocess  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _ensure_dir(EXPERIMENT_DIR)
    logger.info("Experiment directory: %s", EXPERIMENT_DIR)

    input_file = DATA_DIR / "hotpotqa_retrieval.json"
    samples = _load_first_n_samples(input_file, 20)
    logger.info("Loaded %d HotpotQA samples from %s", len(samples), input_file)

    # Prepare retrieval input with LLM-selected docs.
    retrieval_samples = []
    # Prepare ablation input with raw and vector-only answers.
    ablation_samples = []

    for i, sample in enumerate(samples, 1):
        sid = sample["sample_id"]
        question = sample["question"]
        docs = sample.get("retrieved_docs", [])
        logger.info("[%d/%d] Processing %s", i, len(samples), sid)

        selected_docs, selected_titles = _select_docs(question, docs)
        logger.info("[%d/%d] Selected %d docs: %s", i, len(samples), len(selected_docs), selected_titles)

        vector_answer = _answer(question, selected_docs)
        raw_answer = _raw_answer(question)

        retrieval_samples.append(
            {
                "sample_id": sid,
                "question": question,
                "gold_docs": sample.get("gold_docs", []),
                "retrieved_docs": selected_docs,
                "gold_answer": sample.get("gold_answer", ""),
            }
        )

        ablation_samples.append(
            {
                "sample_id": sid,
                "question": question,
                "gold_answer": sample.get("gold_answer", ""),
                "raw_answer": raw_answer,
                "vector_only_answer": vector_answer,
                "vector_only_context": selected_docs,
                "graph_only_answer": "",
                "graph_vector_answer": "",
            }
        )

    retrieval_file = EXPERIMENT_DIR / "hotpotqa_20_llm_retrieval.json"
    ablation_file = EXPERIMENT_DIR / "hotpotqa_20_llm_ablation.json"
    _save_json({"samples": retrieval_samples}, retrieval_file)
    _save_json({"samples": ablation_samples}, ablation_file)

    # Run benchmarks.
    retrieval_baseline = EXPERIMENT_DIR / "hotpotqa_20_llm_retrieval_baseline.json"
    ablation_baseline = EXPERIMENT_DIR / "hotpotqa_20_llm_ablation_baseline.json"

    def run_cmd(args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    r1 = run_cmd(
        [
            sys.executable,
            "-m",
            "hugegraph_llm.benchmark",
            "run",
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
            sys.executable,
            "-m",
            "hugegraph_llm.benchmark",
            "run",
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

    # Save a short summary.
    summary = {
        "experiment_dir": str(EXPERIMENT_DIR),
        "sample_count": len(samples),
        "llm_model": llm_settings.openai_chat_language_model,
        "files": {
            "retrieval_input": str(retrieval_file),
            "ablation_input": str(ablation_file),
            "retrieval_baseline": str(retrieval_baseline),
            "ablation_baseline": str(ablation_baseline),
        },
    }
    summary_file = EXPERIMENT_DIR / "summary.json"
    _save_json(summary, summary_file)
    logger.info("Done. Summary: %s", summary_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
