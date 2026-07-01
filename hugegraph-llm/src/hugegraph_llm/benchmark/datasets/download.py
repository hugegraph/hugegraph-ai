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

    if spec.postprocess == "hotpotqa_corpus":
        _derive_hotpotqa_corpus(
            data_root / "hotpotqa" / "hotpotqa.json", data_root / "hotpotqa" / "hotpotqa_corpus.json"
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


def _derive_hotpotqa_corpus(qa_file: Path, corpus_file: Path) -> None:
    if corpus_file.exists():
        logger.info("Derived corpus already exists: %s", corpus_file)
        return
    try:
        with open(qa_file, "r", encoding="utf-8") as f:
            qa_items = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise DatasetDownloadError(f"Failed to read HotpotQA file {qa_file}: {e}") from e
    if not isinstance(qa_items, list):
        raise DatasetDownloadError(f"Expected {qa_file} to contain a JSON list")

    title_to_text = {}
    for item in qa_items:
        if not isinstance(item, dict):
            continue
        for context_item in item.get("context", []):
            if not isinstance(context_item, list) or len(context_item) != 2:
                continue
            title, sentences = context_item
            text = " ".join(sentences) if isinstance(sentences, list) else str(sentences)
            title_to_text.setdefault(str(title), text)

    corpus_file.parent.mkdir(parents=True, exist_ok=True)
    with open(corpus_file, "w", encoding="utf-8") as f:
        json.dump(
            [{"title": title, "text": text} for title, text in sorted(title_to_text.items())],
            f,
            indent=2,
            ensure_ascii=False,
        )
    logger.info("Derived HotpotQA corpus: %s", corpus_file)


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
