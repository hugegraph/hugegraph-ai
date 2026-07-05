# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate real HugeGraph-AI retrieval outputs for benchmark datasets.

This script takes a retrieval benchmark JSON (with `samples`, each having a
`question` and `retrieved_contexts` text corpus), rebuilds the local Faiss vector
index and the HugeGraph property graph from the corpus, and then runs each
question through the `rag_graph_vector` flow.  The merged retrieval context
and the graph+vector answer are written back to an enriched JSON file.

Usage:
    uv run python -m hugegraph_llm.scripts.benchmark.generate_hugegraph_retrieval_outputs \
        --input <input.json> --output <output.json> [--graph-name <name>] \
        [--topk 20] [--max-workers 1]

    python scripts/benchmark/generate_hugegraph_retrieval_outputs.py \
        --input <input.json> --output <output.json> [--graph-name <name>] \
        [--topk 20] [--max-workers 1]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow the script to be run directly from the repository without installing
# the package first.  `uv run python -m ...` does not need this because the
# package is already on sys.path, but `python scripts/benchmark/...py` does.
REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pyhugegraph.client import PyHugeClient  # noqa: E402

from hugegraph_llm.config import huge_settings, llm_settings  # noqa: E402
from hugegraph_llm.flows import FlowName  # noqa: E402
from hugegraph_llm.flows.scheduler import SchedulerSingleton  # noqa: E402
from hugegraph_llm.indices.vector_index.faiss_vector_store import FaissVectorIndex  # noqa: E402
from hugegraph_llm.models.embeddings.init_embedding import get_embedding  # noqa: E402
from hugegraph_llm.state.ai_state import WkFlowInput  # noqa: E402
from hugegraph_llm.utils.embedding_utils import get_embeddings_parallel  # noqa: E402
from hugegraph_llm.utils.log import log  # noqa: E402

logger = logging.getLogger("generate_hugegraph_retrieval_outputs")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate real HugeGraph-AI retrieval outputs for a benchmark dataset."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input retrieval JSON with a 'samples' list.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path where the enriched retrieval JSON will be written.",
    )
    parser.add_argument(
        "--graph-name",
        default="hugegraph",
        help="HugeGraph graph name to use for indexing and querying (default: hugegraph).",
    )
    parser.add_argument(
        "--topk",
        type=int,
        default=20,
        help="Number of top results to return from the merged graph+vector retrieval (default: 20).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Maximum parallel workers for question processing; default 1 keeps execution serial.",
    )
    parser.add_argument(
        "--max-graph-chunks",
        type=int,
        default=30,
        help="Maximum number of corpus chunks to use for property-graph extraction (default: 30). "
        "The vector index is still built over the full corpus.  A smaller value keeps LLM costs "
        "and runtime bounded while still producing a per-dataset HugeGraph baseline.",
    )
    parser.add_argument(
        "--max-corpus-chars",
        type=int,
        default=32000,
        help="Truncate each corpus chunk to this many characters before indexing and graph "
        "extraction (default: 32000, ~8k tokens).  Lower this for datasets with very long "
        "passages to keep embedding / LLM calls within provider limits.",
    )
    return parser.parse_args()


def setup_logging() -> None:
    """Configure logging to stderr with a consistent format."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Keep the project logger in sync so existing `log.*` calls also go to stderr.
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def load_input(input_path: str) -> Dict[str, Any]:
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "samples" not in data or not isinstance(data["samples"], list):
        raise ValueError("Input JSON must contain a 'samples' list.")
    return data


def collect_corpus(samples: List[Dict[str, Any]], max_chars: int = 32000) -> List[str]:
    """Build a deduplicated list of text chunks from all retrieved_contexts.

    Long benchmark passages (e.g. GraphRAG-Bench Medical) can exceed the
    embedding model's per-input token limit.  We truncate each chunk to
    ``max_chars`` characters (≈ 8k tokens) before indexing so that Jina
    embeddings and property-graph extraction stay within provider limits.
    """
    seen: set = set()
    corpus: List[str] = []
    for sample in samples:
        for doc in sample.get("retrieved_contexts", []):
            if not isinstance(doc, str) or not doc:
                continue
            truncated = doc[:max_chars]
            if truncated not in seen:
                seen.add(truncated)
                corpus.append(truncated)
    return corpus


def clean_indices_and_graph(graph_name: str) -> None:
    """Remove the previous Faiss chunk index and clear HugeGraph data."""
    logger.info("Cleaning vector index for graph '%s'...", graph_name)
    FaissVectorIndex.clean(graph_name, "chunks")

    logger.info("Clearing HugeGraph data for graph '%s'...", graph_name)
    client = PyHugeClient(
        url=huge_settings.graph_url,
        graph=graph_name,
        user=huge_settings.graph_user,
        pwd=huge_settings.graph_pwd,
        graphspace=huge_settings.graph_space,
    )
    client.graphs().clear_graph_all_data()
    logger.info("Graph data cleared.")


def run_scheduler_flow(flow_name: str, *args, **kwargs) -> Any:
    """Convenience wrapper around SchedulerSingleton.schedule_flow."""
    scheduler = SchedulerSingleton.get_instance()
    return scheduler.schedule_flow(flow_name, *args, **kwargs)


DEFAULT_FALLBACK_SCHEMA = {
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "type", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "description", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
    "vertexlabels": [
        {
            "id": 1,
            "name": "Entity",
            "id_strategy": "PRIMARY_KEY",
            "properties": ["name", "type", "description"],
            "primary_keys": ["name"],
            "nullable_keys": ["type", "description"],
        }
    ],
    "edgelabels": [
        {
            "id": 1,
            "name": "RELATED_TO",
            "source_label": "Entity",
            "target_label": "Entity",
            "properties": [],
        }
    ],
}


def _extract_property_names(props: Any) -> List[str]:
    """Return a list of property names from a properties field.

    Supports both the old schema format (list of property name strings) and
    the new BUILD_SCHEMA format (list of {"name": ...} objects).
    """
    if not isinstance(props, list):
        return []
    names: List[str] = []
    for prop in props:
        if isinstance(prop, str):
            names.append(prop)
        elif isinstance(prop, dict) and prop.get("name"):
            names.append(prop["name"])
    return names


def _normalize_schema(schema_str: str) -> str:
    """Normalize an LLM-generated schema so it satisfies CheckSchema/Commit2Graph.

    BUILD_SCHEMA may return either the legacy format (``vertexlabels``,
    ``edgelabels``, ``propertykeys`` with string property lists) or a newer
    compact format (``vertices``, ``edges`` with property objects).  This
    function converts both into the legacy format and repairs missing fields.
    """
    schema = json.loads(schema_str)
    if not isinstance(schema, dict):
        raise ValueError("Schema is not a JSON object.")

    # Accept both ``vertices``/``edges`` and ``vertexlabels``/``edgelabels``.
    raw_vertices = schema.get("vertexlabels") or schema.get("vertices") or []
    raw_edges = schema.get("edgelabels") or schema.get("edges") or []

    if not isinstance(raw_vertices, list) or not isinstance(raw_edges, list):
        logger.warning("LLM schema has invalid vertex/edge containers; using fallback schema.")
        return json.dumps(DEFAULT_FALLBACK_SCHEMA, ensure_ascii=False, indent=2)

    if not raw_vertices:
        logger.warning("LLM schema has no vertex labels; using fallback schema.")
        return json.dumps(DEFAULT_FALLBACK_SCHEMA, ensure_ascii=False, indent=2)

    propertykeys: List[Dict[str, Any]] = []
    property_set: set = set()

    def _ensure_property(prop_name: str, data_type: str = "TEXT", cardinality: str = "SINGLE") -> None:
        if prop_name not in property_set:
            propertykeys.append({"name": prop_name, "data_type": data_type, "cardinality": cardinality})
            property_set.add(prop_name)

    vertexlabels: List[Dict[str, Any]] = []
    for idx, vertex in enumerate(raw_vertices, start=1):
        if not isinstance(vertex, dict):
            continue
        name = vertex.get("name")
        if not name:
            continue
        prop_names = _extract_property_names(vertex.get("properties"))
        if not prop_names:
            prop_names = ["name"]
        for prop_name in prop_names:
            _ensure_property(prop_name)
        primary_keys = vertex.get("primary_keys")
        if not isinstance(primary_keys, list) or not primary_keys:
            primary_keys = [prop_names[0]]
        primary_keys = [p for p in primary_keys if p in prop_names]
        if not primary_keys:
            primary_keys = [prop_names[0]]
        nullable_keys = vertex.get("nullable_keys")
        if not isinstance(nullable_keys, list):
            nullable_keys = [p for p in prop_names if p not in primary_keys]
        else:
            nullable_keys = [p for p in nullable_keys if p in prop_names and p not in primary_keys]
        # The downstream Commit2Graph path always creates vertex labels with
        # ``usePrimaryKeyId()``.  If the LLM produced a different id_strategy
        # (e.g. CUSTOMIZE_STRING) the import logic would pass an explicit id
        # to a PRIMARY_KEY label and HugeGraph rejects it.  Force PRIMARY_KEY
        # here so the normalized schema and the created schema agree.
        vertexlabels.append(
            {
                "id": vertex.get("id", idx),
                "name": name,
                "id_strategy": "PRIMARY_KEY",
                "properties": prop_names,
                "primary_keys": primary_keys,
                "nullable_keys": nullable_keys,
            }
        )

    if not vertexlabels:
        logger.warning("No valid vertex labels after normalization; using fallback schema.")
        return json.dumps(DEFAULT_FALLBACK_SCHEMA, ensure_ascii=False, indent=2)

    edgelabels: List[Dict[str, Any]] = []
    for idx, edge in enumerate(raw_edges, start=1):
        if not isinstance(edge, dict):
            continue
        name = edge.get("name")
        source_label = edge.get("source_label")
        target_label = edge.get("target_label")
        if not name or not source_label or not target_label:
            continue
        prop_names = _extract_property_names(edge.get("properties"))
        for prop_name in prop_names:
            _ensure_property(prop_name)
        edgelabels.append(
            {
                "id": edge.get("id", idx),
                "name": name,
                "source_label": source_label,
                "target_label": target_label,
                "properties": prop_names,
            }
        )

    normalized = {
        "propertykeys": propertykeys,
        "vertexlabels": vertexlabels,
        "edgelabels": edgelabels,
    }
    return json.dumps(normalized, ensure_ascii=False, indent=2)


def _schema_is_valid(schema: Dict[str, Any]) -> bool:
    """Return True if the LLM-generated schema has the minimal required shape."""
    if not isinstance(schema, dict):
        return False
    raw_vertices = schema.get("vertexlabels") or schema.get("vertices")
    raw_edges = schema.get("edgelabels") or schema.get("edges")
    if not isinstance(raw_vertices, list) or not isinstance(raw_edges, list):
        return False
    if not raw_vertices:
        return False
    for vertex in raw_vertices:
        if not isinstance(vertex, dict):
            return False
        if not vertex.get("name"):
            return False
        props = _extract_property_names(vertex.get("properties"))
        if not props:
            return False
    return True


def _build_schema_with_retry(corpus: List[str], max_attempts: int = 3) -> str:
    """Call BUILD_SCHEMA and retry until a valid schema is produced.

    Flow execution may raise (e.g. an LLM returned truncated/invalid JSON),
    so each attempt is wrapped in try/except and we fall back to a generic
    schema instead of aborting the whole retrieval generation pipeline.
    """
    last_error: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        logger.info("Building graph schema from corpus (attempt %d/%d)...", attempt, max_attempts)
        try:
            schema_str = run_scheduler_flow(FlowName.BUILD_SCHEMA, corpus, None, None)
        except Exception as exc:  # pylint: disable=broad-except
            last_error = f"flow raised: {exc}"
            logger.warning("BUILD_SCHEMA attempt %d raised an exception: %s", attempt, exc)
            continue
        if not schema_str or not schema_str.strip():
            last_error = "empty schema"
            continue
        try:
            schema = json.loads(schema_str)
            if _schema_is_valid(schema):
                return schema_str
            last_error = "schema missing required fields"
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON: {exc}"
    logger.warning("BUILD_SCHEMA failed after %d attempts (%s); using fallback schema.", max_attempts, last_error)
    return json.dumps(DEFAULT_FALLBACK_SCHEMA, ensure_ascii=False, indent=2)


def _create_property_key(schema, prop: Dict[str, Any]) -> None:
    """Create a property key in HugeGraph if it does not exist."""
    name = prop["name"]
    data_type = prop.get("data_type", "TEXT").upper()
    cardinality = prop.get("cardinality", "SINGLE").upper()
    pk = schema.propertyKey(name)
    if data_type in {"INT", "INTEGER"}:
        pk.asInt()
    elif data_type == "LONG":
        pk.asLong()
    elif data_type in {"FLOAT", "DOUBLE"}:
        pk.asDouble()
    elif data_type == "DATE":
        pk.asDate()
    else:
        pk.asText()
    if cardinality == "LIST":
        pk.valueList()
    elif cardinality == "SET":
        pk.valueSet()
    else:
        pk.valueSingle()
    pk.ifNotExist().create()


def _create_vertex_label(schema, vertex: Dict[str, Any]) -> None:
    """Create a vertex label in HugeGraph if it does not exist."""
    name = vertex["name"]
    properties = vertex.get("properties", [])
    primary_keys = vertex.get("primary_keys", [])
    nullable_keys = vertex.get("nullable_keys", [])
    builder = schema.vertexLabel(name)
    if properties:
        builder.properties(*properties)
    if nullable_keys:
        builder.nullableKeys(*nullable_keys)
    builder.usePrimaryKeyId()
    if primary_keys:
        builder.primaryKeys(*primary_keys)
    builder.ifNotExist().create()


def _create_edge_label(schema, edge: Dict[str, Any]) -> None:
    """Create an edge label in HugeGraph if it does not exist."""
    name = edge["name"]
    source_label = edge["source_label"]
    target_label = edge["target_label"]
    properties = edge.get("properties", [])
    builder = schema.edgeLabel(name).sourceLabel(source_label).targetLabel(target_label)
    if properties:
        builder.properties(*properties).nullableKeys(*properties)
    builder.ifNotExist().create()


def _ensure_hugegraph_schema(schema_str: str) -> None:
    """Ensure the normalized schema exists in HugeGraph even with no data.

    ``rag_graph_vector`` needs a non-empty HugeGraph schema to run.  If graph
    extraction produced no vertices/edges, ``IMPORT_GRAPH_DATA`` is skipped and
    the schema may remain empty.  This function creates the schema elements
    directly so the downstream RAG flow can proceed.
    """
    logger.info("Ensuring HugeGraph schema exists...")
    client = PyHugeClient(
        url=huge_settings.graph_url,
        graph=huge_settings.graph_name,
        user=huge_settings.graph_user,
        pwd=huge_settings.graph_pwd,
        graphspace=huge_settings.graph_space,
    )
    hg_schema = client.schema()
    schema = json.loads(schema_str)

    for prop in schema.get("propertykeys", []):
        if isinstance(prop, dict) and prop.get("name"):
            _create_property_key(hg_schema, prop)

    for vertex in schema.get("vertexlabels", []):
        if isinstance(vertex, dict) and vertex.get("name"):
            _create_vertex_label(hg_schema, vertex)

    for edge in schema.get("edgelabels", []):
        if isinstance(edge, dict) and edge.get("name"):
            _create_edge_label(hg_schema, edge)

    logger.info("HugeGraph schema ensured.")


def build_indexes_and_graph(corpus: List[str], max_graph_chunks: int) -> None:
    """Build vector index and HugeGraph property graph from the corpus.

    The full corpus is indexed for vector retrieval, but only the first
    ``max_graph_chunks`` chunks are passed to property-graph extraction to keep
    LLM costs and runtime bounded.
    """
    logger.info("Building vector index over %d chunks...", len(corpus))
    embedding = get_embedding(llm_settings)
    embeddings = asyncio.run(get_embeddings_parallel(embedding, corpus))
    vector_index = FaissVectorIndex.from_name(embedding.get_embedding_dim(), huge_settings.graph_name, "chunks")
    vector_index.add(embeddings, corpus)
    vector_index.save_index_by_name(huge_settings.graph_name, "chunks")
    logger.info("Vector index built with %d vectors.", len(embeddings))

    graph_corpus = corpus[:max_graph_chunks]
    logger.info("Using %d chunks for property-graph extraction.", len(graph_corpus))

    if not graph_corpus:
        logger.warning("max_graph_chunks is 0; skipping LLM graph extraction and using empty graph.")
        fallback_schema = json.dumps(DEFAULT_FALLBACK_SCHEMA, ensure_ascii=False, indent=2)
        _ensure_hugegraph_schema(fallback_schema)
        return

    schema_str = _build_schema_with_retry(graph_corpus)
    try:
        schema_str = _normalize_schema(schema_str)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Failed to normalize schema (%s); using raw schema.", exc)
    logger.info("Schema ready (length %d).", len(schema_str))

    logger.info("Extracting property graph from corpus...")
    graph_data_json = run_scheduler_flow(
        FlowName.GRAPH_EXTRACT,
        schema_str,
        graph_corpus,
        "",
        "property_graph",
    )
    logger.info("Graph extraction finished (length %d).", len(graph_data_json) if graph_data_json else 0)

    graph_data = json.loads(graph_data_json) if isinstance(graph_data_json, str) else graph_data_json
    if not graph_data or (not graph_data.get("vertices") and not graph_data.get("edges")):
        logger.warning("Graph extraction returned empty vertices/edges; ensuring schema exists without data.")
        _ensure_hugegraph_schema(schema_str)
        return

    logger.info("Importing graph data into HugeGraph...")
    run_scheduler_flow(FlowName.IMPORT_GRAPH_DATA, graph_data_json, schema_str)
    logger.info("Graph data imported.")


def run_rag_graph_vector(query: str, topk: int) -> Dict[str, Any]:
    """Run the rag_graph_vector flow and return both state and post_deal result.

    This mirrors SchedulerSingleton.schedule_flow but also captures the
    WkFlowState so that the merged retrieval context can be extracted.
    """
    scheduler = SchedulerSingleton.get_instance()
    manager = scheduler.pipeline_pool[FlowName.RAG_GRAPH_VECTOR]["manager"]
    flow = scheduler.pipeline_pool[FlowName.RAG_GRAPH_VECTOR]["flow"]

    pipeline = manager.fetch()
    if pipeline is None:
        pipeline = flow.build_flow(query=query, rerank_method="bleu", topk_return_results=topk)
        status = pipeline.init()
        if status.isErr():
            raise RuntimeError(f"rag_graph_vector init failed: {status.getInfo()}")
        status = pipeline.run()
        if status.isErr():
            manager.add(pipeline)
            raise RuntimeError(f"rag_graph_vector run failed: {status.getInfo()}")
        state = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        result = flow.post_deal(pipeline)
        manager.add(pipeline)
        return {"state": state, "result": result}

    try:
        prepared_input: WkFlowInput = pipeline.getGParamWithNoEmpty("wkflow_input")
        flow.prepare(
            prepared_input,
            query=query,
            rerank_method="bleu",
            topk_return_results=topk,
        )
        status = pipeline.run()
        if status.isErr():
            raise RuntimeError(f"rag_graph_vector run failed: {status.getInfo()}")
        state = pipeline.getGParamWithNoEmpty("wkflow_state").to_json()
        result = flow.post_deal(pipeline)
    finally:
        manager.release(pipeline)
    return {"state": state, "result": result}


def _doc_ids_for_contexts(contexts: List[Any], original_contexts: List[Any], original_doc_ids: List[Any]) -> List[str]:
    context_to_id = {
        str(context): str(doc_id)
        for context, doc_id in zip(original_contexts, original_doc_ids)
        if isinstance(context, str) and doc_id is not None
    }
    doc_ids = []
    for idx, context in enumerate(contexts):
        doc_ids.append(context_to_id.get(str(context), f"retrieved_{idx}"))
    return doc_ids


def process_sample(
    sample: Dict[str, Any],
    topk: int,
) -> Dict[str, Any]:
    """Run one sample through rag_graph_vector and enrich it."""
    question = sample.get("question", "")
    sample_id = sample.get("sample_id", "unknown")
    original_contexts = sample.get("retrieved_contexts", [])
    original_doc_ids = sample.get("retrieved_doc_ids", [])

    if not question:
        logger.warning("Sample %s has no question; leaving unchanged.", sample_id)
        sample["graph_vector_answer"] = ""
        return sample

    logger.info("Processing sample %s: %s", sample_id, question[:80])
    try:
        output = run_rag_graph_vector(question, topk)
        state = output.get("state", {})
        result = output.get("result", {})

        merged = state.get("merged_result")
        if merged is None:
            merged = state.get("vector_result", [])
        if not isinstance(merged, list):
            merged = [merged] if merged else []

        sample["retrieved_contexts"] = merged
        sample["retrieved_doc_ids"] = _doc_ids_for_contexts(merged, original_contexts, original_doc_ids)
        sample["graph_vector_answer"] = result.get("graph_vector_answer", "")
        logger.info(
            "Sample %s completed: %d merged docs, answer length %d.",
            sample_id,
            len(merged),
            len(sample["graph_vector_answer"]),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Sample %s failed: %s", sample_id, exc)
        logger.debug(traceback.format_exc())
        sample["retrieved_contexts"] = original_contexts
        sample["retrieved_doc_ids"] = original_doc_ids
        sample["graph_vector_answer"] = ""

    return sample


def main() -> None:
    args = parse_args()
    setup_logging()

    logger.info("Loading input from %s", args.input)
    data = load_input(args.input)
    samples = data["samples"]
    logger.info("Loaded %d samples.", len(samples))

    corpus = collect_corpus(samples, args.max_corpus_chars)
    if not corpus:
        raise ValueError("No text corpus found in retrieved_contexts; nothing to index.")
    logger.info("Collected %d unique corpus chunks.", len(corpus))

    # Make all downstream flows target the requested graph/index namespace.
    huge_settings.graph_name = args.graph_name
    logger.info("Using graph name: %s", args.graph_name)

    clean_indices_and_graph(args.graph_name)
    build_indexes_and_graph(corpus, args.max_graph_chunks)

    logger.info("Processing %d samples (max_workers=%d)...", len(samples), args.max_workers)
    enriched_samples: List[Dict[str, Any]] = []
    if args.max_workers <= 1:
        for sample in samples:
            enriched_samples.append(process_sample(sample, args.topk))
    else:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_to_idx = {
                executor.submit(process_sample, sample, args.topk): idx for idx, sample in enumerate(samples)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    enriched_samples.append((idx, future.result()))
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Unexpected error for sample index %d: %s", idx, exc)
                    enriched_samples.append((idx, samples[idx]))
        enriched_samples.sort(key=lambda x: x[0])
        enriched_samples = [s for _, s in enriched_samples]

    output_data = {**data, "samples": enriched_samples}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    logger.info("Wrote enriched output to %s", args.output)


if __name__ == "__main__":
    main()
