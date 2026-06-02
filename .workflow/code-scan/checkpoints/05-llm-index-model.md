# T2 LLM Index and Model Checkpoint

Status: completed

## Scope

- `hugegraph-llm/src/hugegraph_llm/indices/`
- `hugegraph-llm/src/hugegraph_llm/models/`
- `hugegraph-llm/src/hugegraph_llm/utils/`
- `hugegraph-llm/src/tests/indices/`
- `hugegraph-llm/src/tests/models/`

## Findings

- `CS-015`: LiteLLM embedding factory crashes for advertised config.
- `CS-016`: OpenAI wrapper returns provider failures as normal model text.
- `CS-017`: embedding dimension probing hides provider failures.
- `CS-024`: LiteLLM sync streaming violates `BaseLLM` contract.
- `CS-025`: `dis_threshold` has incompatible backend semantics.
- `CS-026`: graph backup can report success with empty `schema.json`.
- `CS-029`: `get_embeddings_parallel()` launches all batches concurrently.

## Test-quality Notes

- Added `FIXME:` comments in OpenAI and Faiss tests.
- Recorded missing tests for embedding factories, LiteLLM streaming,
  backend thresholds, and bounded embedding concurrency.
