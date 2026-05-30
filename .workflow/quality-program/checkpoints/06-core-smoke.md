# G5 Core Smoke Checkpoint

## Status

Complete.

## Completed Scope

- Added deterministic smoke fixture data under `hugegraph-llm/src/tests/data/quality_program/`.
- Added KG smoke that imports production `Commit2Graph` and `FetchGraphData`, writes fixture graph data to HugeGraph `1.7.0`, and verifies counts through production fetch code.
- Added GraphRAG smoke that imports production `BuildVectorIndex`, `VectorIndexQuery`, and `MergeDedupRerank` with deterministic embedding and in-memory vector fixtures.
- Added Text2Gremlin smoke that imports production `GremlinGenerateSynthesize` and `Text2GremlinFlow` with deterministic `FakeLLM` output.
- Inspected existing integration tests and left the mock-only legacy pipeline tests in place while replacing their gate value with production-code smoke tests in this goal.

## Commands Run

```bash
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -v --tb=short
uv run pytest hugegraph-llm/src/tests/integration -m "smoke and not hugegraph" -v --tb=short
uv run ruff format --check hugegraph-llm/src/tests/integration/test_core_kg_smoke.py hugegraph-llm/src/tests/integration/test_core_graphrag_smoke.py hugegraph-llm/src/tests/integration/test_core_text2gremlin_smoke.py
uv run ruff check hugegraph-llm/src/tests/integration/test_core_kg_smoke.py hugegraph-llm/src/tests/integration/test_core_graphrag_smoke.py hugegraph-llm/src/tests/integration/test_core_text2gremlin_smoke.py
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -q
```

## Verification Result

| Layer | Command | Result |
|---|---|---|
| Core smoke including HugeGraph | `HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -v --tb=short` | `4 passed, 15 deselected` |
| Core smoke without HugeGraph | `uv run pytest hugegraph-llm/src/tests/integration -m "smoke and not hugegraph" -v --tb=short` | `3 passed, 16 deselected` |
| Formatting | `uv run ruff format --check ...` | `3 files already formatted` |
| Lint | `uv run ruff check ...` | `All checks passed` |

## Weak Integration Test Audit

| File | Finding | G5 action |
|---|---|---|
| `hugegraph-llm/src/tests/integration/test_kg_construction.py` | Defines local mock `OpenAILLM` and `KGConstructor` classes instead of production pipeline code. | Added `test_core_kg_smoke.py` with production `Commit2Graph` and `FetchGraphData`; full rewrite deferred. |
| `hugegraph-llm/src/tests/integration/test_graph_rag_pipeline.py` | Defines local mock `RAGPipeline` instead of production flow classes. | Added `test_core_graphrag_smoke.py` with production vector/rerank operators; full rewrite deferred. |
| `hugegraph-llm/src/tests/integration/test_rag_pipeline.py` | Existing mock-heavy coverage remains outside the new smoke gate. | New smoke gate is the authoritative G5 quality signal. |

## Production Changes

None.

## Failure Classification

- No smoke gate blocker remains.
- GraphRAG smoke emits BLEU-related warnings from NLTK for short deterministic strings; test assertions are stable and no flaky failure was observed.

## Files Touched

- `.workflow/quality-program/checkpoints/06-core-smoke.md`
- `.workflow/quality-program/quality-state.json`
- `docs/superpowers/plans/2026-05-31-hugegraph-ai-quality-program.md`
- `hugegraph-llm/src/tests/data/quality_program/kg_text.txt`
- `hugegraph-llm/src/tests/data/quality_program/kg_graph_output.json`
- `hugegraph-llm/src/tests/data/quality_program/graphrag_documents.json`
- `hugegraph-llm/src/tests/data/quality_program/text2gremlin_schema.json`
- `hugegraph-llm/src/tests/integration/test_core_kg_smoke.py`
- `hugegraph-llm/src/tests/integration/test_core_graphrag_smoke.py`
- `hugegraph-llm/src/tests/integration/test_core_text2gremlin_smoke.py`

## Next Goal Readiness

G6 can begin. Unit/contract, HugeGraph boundary, and core smoke gates now have deterministic local commands.
