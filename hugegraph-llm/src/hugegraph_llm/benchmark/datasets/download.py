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

"""Download and validate raw public benchmark datasets."""

import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Iterable, List

import requests

from hugegraph_llm.benchmark.datasets.registry import (
    DatasetSpec,
    DownloadFile,
    expand_dataset_names,
    get_dataset_spec,
)

logger = logging.getLogger(__name__)


class DatasetDownloadError(Exception):
    """Raised when a raw public dataset is missing or cannot be downloaded."""


def missing_files(spec: DatasetSpec, data_root: Path) -> List[str]:
    """Return expected raw files that are absent under ``data_root``."""
    return [rel_path for rel_path in spec.expected_files if not (data_root / rel_path).exists()]


def ensure_dataset_available(dataset: str, data_root: Path, download: bool = False, force: bool = False) -> None:
    """Ensure all raw files for ``dataset`` exist, optionally downloading them."""
    data_root = data_root.resolve()
    for name in expand_dataset_names(dataset):
        spec = get_dataset_spec(name)
        missing = missing_files(spec, data_root)
        if not missing:
            continue
        if download:
            download_dataset(name, data_root, force=force)
            missing = missing_files(spec, data_root)
        if missing:
            raise DatasetDownloadError(_format_missing_files(spec, data_root, missing))


def download_dataset(dataset: str, data_root: Path, force: bool = False) -> None:
    """Download one concrete dataset into the raw data cache."""
    spec = get_dataset_spec(dataset)
    if not spec.downloadable:
        raise DatasetDownloadError(_format_manual_dataset(spec, data_root))

    data_root.mkdir(parents=True, exist_ok=True)
    logger.info("Preparing raw dataset %s in %s", spec.name, data_root)
    for file_spec in spec.download_files:
        if file_spec.kind == "file":
            _download_file(file_spec.url, data_root / file_spec.path, force=force)
        elif file_spec.kind == "zip":
            _download_and_extract_zip(file_spec, data_root, force=force)
        else:
            raise DatasetDownloadError(f"Unsupported download kind {file_spec.kind!r} for {spec.name}")

    if spec.postprocess == "hotpotqa":
        _postprocess_hotpotqa_like(
            data_root / "hotpotqa" / "hotpotqa_dev_distractor.parquet",
            data_root / "hotpotqa" / "hotpotqa.json",
            data_root / "hotpotqa" / "hotpotqa_corpus.json",
        )
    elif spec.postprocess == "2wikimultihopqa":
        _postprocess_hotpotqa_like(
            data_root / "2wikimultihopqa" / "2wikimultihopqa_dev.parquet",
            data_root / "2wikimultihopqa" / "2wikimultihopqa.json",
            data_root / "2wikimultihopqa" / "2wikimultihopqa_corpus.json",
        )
    elif spec.postprocess == "musique":
        _postprocess_musique(
            data_root / "musique" / "musique_ans_v1.0_dev.jsonl",
            data_root / "musique" / "musique.json",
        )


def _download_file(url: str, path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        logger.info("Raw file already exists: %s", path)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".part")
    logger.info("Downloading %s", url)
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
    except requests.RequestException as e:
        tmp_path.unlink(missing_ok=True)
        raise DatasetDownloadError(f"Failed to download {url}: {e}") from e

    tmp_path.replace(path)
    logger.info("Saved raw file: %s", path)


def _download_and_extract_zip(file_spec: DownloadFile, data_root: Path, force: bool = False) -> None:
    archive_name = file_spec.url.rstrip("/").rsplit("/", 1)[-1] or "dataset.zip"
    archive_path = data_root / ".downloads" / archive_name
    _download_file(file_spec.url, archive_path, force=force)
    target_dir = data_root / file_spec.path
    _extract_zip(archive_path, target_dir, strip_components=file_spec.strip_components)


def _extract_zip(archive_path: Path, target_dir: Path, strip_components: int = 0) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()

    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                rel_path = _stripped_zip_path(member.filename, strip_components)
                if rel_path is None:
                    continue
                destination = (target_dir / rel_path).resolve()
                try:
                    destination.relative_to(target_root)
                except ValueError:
                    raise DatasetDownloadError(f"Unsafe path in archive {archive_path}: {member.filename}")
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(destination, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile as e:
        raise DatasetDownloadError(f"Invalid zip archive {archive_path}: {e}") from e

    logger.info("Extracted %s to %s", archive_path, target_dir)


def _stripped_zip_path(member_name: str, strip_components: int) -> Path | None:
    parts = [part for part in Path(member_name).parts if part not in ("", ".")]
    if len(parts) <= strip_components:
        return None
    parts = parts[strip_components:]
    if any(part == ".." for part in parts):
        raise DatasetDownloadError(f"Unsafe path in archive: {member_name}")
    return Path(*parts)


def _postprocess_hotpotqa_like(
    parquet_file: Path, qa_file: Path, corpus_file: Path
) -> None:
    """Convert a HotpotQA/2Wiki HF parquet into the list-of-dicts JSON the converter expects.

    The converter reads ``qa_file`` as a list of items shaped like the original
    HotpotQA release: ``{context: [[title, [sentences]], ...],
    supporting_facts: [[title, sent_id], ...], _id, question, answer}``.
    The HF parquet stores ``context``/``supporting_facts`` as struct-of-arrays,
    so we expand them back. ``corpus_file`` is derived as ``[{title, text}]``.
    """
    if qa_file.exists() and corpus_file.exists():
        logger.info("Derived HotpotQA-like files already exist: %s, %s", qa_file, corpus_file)
        return
    try:
        import pandas as pd
    except ImportError as e:
        raise DatasetDownloadError("pandas is required to parse downloaded parquet files") from e

    try:
        df = pd.read_parquet(parquet_file)
    except Exception as e:
        raise DatasetDownloadError(f"Failed to read parquet {parquet_file}: {e}") from e

    qa_items = []
    title_to_text = {}
    for _, row in df.iterrows():
        ctx = row["context"]
        # Some mirrors (2Wiki) store context/supporting_facts as JSON *strings*.
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except json.JSONDecodeError:
                ctx = []
        # context struct: {"title": [str], "sentences": [[str]]} (HF) or list-of-lists (legacy)
        if isinstance(ctx, dict):
            titles = list(ctx.get("title", []))
            sentences = list(ctx.get("sentences", []))
            context_list = [
                [str(t), list(s) if hasattr(s, "__iter__") else [str(s)]]
                for t, s in zip(titles, sentences)
            ]
        else:
            context_list = [list(c) for c in ctx]

        sf = row["supporting_facts"]
        if isinstance(sf, str):
            try:
                sf = json.loads(sf)
            except json.JSONDecodeError:
                sf = []
        if isinstance(sf, dict):
            sf_titles = list(sf.get("title", []))
            sf_ids = list(sf.get("sent_id", sf.get("sentence_ids", [])))
            supporting = [[str(t), int(i)] for t, i in zip(sf_titles, sf_ids)]
        else:
            supporting = [list(x) for x in sf]

        item = {
            "_id": str(row.get("id", row.get("_id", ""))),
            "question": str(row.get("question", "")),
            "answer": str(row.get("answer", "")),
            "context": context_list,
            "supporting_facts": supporting,
        }
        qa_items.append(item)
        for title, sents in context_list:
            text = " ".join(sents) if isinstance(sents, list) else str(sents)
            title_to_text.setdefault(str(title), text)

    qa_file.parent.mkdir(parents=True, exist_ok=True)
    with open(qa_file, "w", encoding="utf-8") as f:
        json.dump(qa_items, f, ensure_ascii=False)
    with open(corpus_file, "w", encoding="utf-8") as f:
        json.dump(
            [{"title": t, "text": txt} for t, txt in sorted(title_to_text.items())],
            f,
            indent=2,
            ensure_ascii=False,
        )
    logger.info("Derived %s (%d items) and %s", qa_file, len(qa_items), corpus_file)


def _postprocess_musique(jsonl_file: Path, qa_file: Path) -> None:
    """Convert MuSiQue dev jsonl into the list-of-dicts JSON the converter expects.

    The converter reads ``qa_file`` as a list of items with ``paragraphs`` (each
    carrying ``title``/``paragraph_text``/``is_supporting``), ``id``, ``question``,
    ``answer``. The HF jsonl already matches this shape, so we just rewrap it.
    """
    if qa_file.exists():
        logger.info("Derived MuSiQue file already exists: %s", qa_file)
        return
    items = []
    try:
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
    except (OSError, json.JSONDecodeError) as e:
        raise DatasetDownloadError(f"Failed to read MuSiQue jsonl {jsonl_file}: {e}") from e

    qa_file.parent.mkdir(parents=True, exist_ok=True)
    with open(qa_file, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    logger.info("Derived %s (%d items)", qa_file, len(items))


def _format_missing_files(spec: DatasetSpec, data_root: Path, missing: Iterable[str]) -> str:
    missing_lines = "\n".join(f"  - {path}" for path in missing)
    message = [
        f"Raw dataset files are missing for {spec.name} ({spec.title}).",
        f"Data root: {data_root}",
        "Missing files:",
        missing_lines,
    ]
    if spec.downloadable:
        message.extend(
            [
                "Run with --download to fetch the registered source into the raw cache, for example:",
                (
                    "  python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets "
                    f"--dataset {spec.name} --download --cache-dir {data_root}"
                ),
            ]
        )
    else:
        message.append(_format_manual_dataset(spec, data_root))
    if spec.notes:
        message.append(f"Note: {spec.notes}")
    message.append(f"Source: {spec.source_url}")
    return "\n".join(message)


def _format_manual_dataset(spec: DatasetSpec, data_root: Path) -> str:
    expected_lines = "\n".join(f"  - {path}" for path in spec.expected_files)
    return "\n".join(
        [
            f"Automatic download is not enabled for {spec.name} ({spec.title}).",
            f"Place the raw files under {data_root}:",
            expected_lines,
            f"Source: {spec.source_url}",
        ]
    )
