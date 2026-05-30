# G4 Parser API Operator Checkpoint

## Status

Complete.

## Completed Scope

- Added deterministic `FakeLLM` fixture for parser and operator tests.
- Expanded property graph parser contracts for fenced JSON, malformed JSON, numeric vertex IDs, and duplicate vertices/edges.
- Expanded keyword parser contracts for fenced output, empty provider output, duplicate keywords, malformed items, and non-keyword provider text.
- Expanded Gremlin generator contracts for explanation-plus-code, multiple candidate blocks, and empty deterministic LLM output.
- Expanded public FastAPI route contracts for graph, LLM, embedding, reranker config mapping, invalid request validation, and callback exception response shape.
- Expanded provider wrapper contracts for OpenAI malformed SDK responses, LiteLLM success/malformed responses, and Ollama missing `embed` methods.
- No real LLM, embedding, reranker, vector DB, or UI credentials were required.

## Red Test Observed

```text
test_llm_config_api_passes_openai_fields_to_apply_llm_conf
  failed with ValueError: "LLMConfig" object has no field "llm_type"
```

## Production Fix

| File | Change | Proving test |
|---|---|---|
| `hugegraph-llm/src/hugegraph_llm/api/rag_api.py` | Map `/config/llm` to existing `llm_settings.chat_llm_type` instead of nonexistent `llm_settings.llm_type`. | `uv run pytest hugegraph-llm/src/tests/api -m "unit or contract" -v --tb=short` |

## Commands Run

```bash
uv run ruff format hugegraph-llm/src/tests/fixtures/fake_llm.py hugegraph-llm/src/tests/operators/llm_op/test_property_graph_extract.py hugegraph-llm/src/tests/operators/llm_op/test_keyword_extract.py hugegraph-llm/src/tests/operators/llm_op/test_gremlin_generate.py hugegraph-llm/src/tests/api/test_rag_api.py hugegraph-llm/src/tests/models/llms/test_openai_client.py hugegraph-llm/src/tests/models/llms/test_litellm_client.py hugegraph-llm/src/tests/models/embeddings/test_ollama_embedding.py
uv run pytest hugegraph-llm/src/tests/operators/llm_op -m "unit or contract" -v --tb=short
uv run pytest hugegraph-llm/src/tests/api -m "unit or contract" -v --tb=short
uv run pytest hugegraph-llm/src/tests/models -m "unit or contract" -v --tb=short
uv run ruff format --check hugegraph-llm/src/hugegraph_llm/api/rag_api.py hugegraph-llm/src/tests/fixtures/fake_llm.py hugegraph-llm/src/tests/operators/llm_op/test_property_graph_extract.py hugegraph-llm/src/tests/operators/llm_op/test_keyword_extract.py hugegraph-llm/src/tests/operators/llm_op/test_gremlin_generate.py hugegraph-llm/src/tests/api/test_rag_api.py hugegraph-llm/src/tests/models/llms/test_openai_client.py hugegraph-llm/src/tests/models/llms/test_litellm_client.py hugegraph-llm/src/tests/models/embeddings/test_ollama_embedding.py
uv run ruff check hugegraph-llm/src/hugegraph_llm/api/rag_api.py hugegraph-llm/src/tests/fixtures/fake_llm.py hugegraph-llm/src/tests/operators/llm_op/test_property_graph_extract.py hugegraph-llm/src/tests/operators/llm_op/test_keyword_extract.py hugegraph-llm/src/tests/operators/llm_op/test_gremlin_generate.py hugegraph-llm/src/tests/api/test_rag_api.py hugegraph-llm/src/tests/models/llms/test_openai_client.py hugegraph-llm/src/tests/models/llms/test_litellm_client.py hugegraph-llm/src/tests/models/embeddings/test_ollama_embedding.py
git diff --check
```

## Verification Result

| Layer | Command | Result |
|---|---|---|
| LLM parser/operator contracts | `uv run pytest hugegraph-llm/src/tests/operators/llm_op -m "unit or contract" -v --tb=short` | `68 passed` |
| API public contracts | `uv run pytest hugegraph-llm/src/tests/api -m "unit or contract" -v --tb=short` | `6 passed` |
| Provider wrapper contracts | `uv run pytest hugegraph-llm/src/tests/models -m "unit or contract" -v --tb=short` | `26 passed, 2 skipped, 17 deselected` |
| Formatting | `uv run ruff format --check ...` | `9 files already formatted` |
| Lint | `uv run ruff check ...` | `All checks passed` |

## Files Touched

- `.workflow/quality-program/checkpoints/05-parser-api-operator.md`
- `.workflow/quality-program/quality-state.json`
- `.workflow/quality-program/reports/production-change-ledger.md`
- `docs/superpowers/plans/2026-05-31-hugegraph-ai-quality-program.md`
- `hugegraph-llm/src/hugegraph_llm/api/rag_api.py`
- `hugegraph-llm/src/tests/fixtures/fake_llm.py`
- `hugegraph-llm/src/tests/operators/llm_op/test_property_graph_extract.py`
- `hugegraph-llm/src/tests/operators/llm_op/test_keyword_extract.py`
- `hugegraph-llm/src/tests/operators/llm_op/test_gremlin_generate.py`
- `hugegraph-llm/src/tests/api/test_rag_api.py`
- `hugegraph-llm/src/tests/models/llms/test_openai_client.py`
- `hugegraph-llm/src/tests/models/llms/test_litellm_client.py`
- `hugegraph-llm/src/tests/models/embeddings/test_ollama_embedding.py`

## Failure Classification

- API field mapping contract gap: `/config/llm` targeted a nonexistent Pydantic settings field.
- No parser, operator, provider-wrapper, or external credential blocker remains in G4.

## Next Goal Readiness

G5 can begin. Deterministic parser, API, and provider wrapper suites are available without external credentials.
