# Test-quality Ledger

## Required FIXME Comments

Added specific `FIXME:` comments in these files:

- `hugegraph-llm/src/tests/api/test_rag_api.py`
- `hugegraph-llm/src/tests/config/test_config.py`
- `hugegraph-llm/src/tests/config/test_prompt_config.py`
- `hugegraph-llm/src/tests/models/llms/test_openai_client.py`
- `hugegraph-llm/src/tests/indices/test_faiss_vector_index.py`
- `hugegraph-llm/src/tests/operators/hugegraph_op/test_commit_to_hugegraph.py`
- `hugegraph-llm/src/tests/operators/hugegraph_op/test_commit_to_hugegraph_load_into_graph.py`
- `hugegraph-llm/src/tests/operators/index_op/test_vector_index_query.py`
- `hugegraph-python-client/src/tests/api/test_auth_routing.py`
- `hugegraph-python-client/src/tests/api/test_graph.py`
- `hugegraph-python-client/src/tests/api/test_schema.py`
- `hugegraph-python-client/src/tests/api/test_gremlin.py`

## Weak or Ineffective Tests

| ID | Paths | Weakness |
|---|---|---|
| TQ-002 | `test_commit_to_hugegraph.py`, `test_commit_to_hugegraph_load_into_graph.py` | Helper patching bypasses branchy graph import logic. |
| TQ-003 | `test_rag_api.py` | Missing `/rag` and `/rag/graph` happy-path response-shaping tests. |
| TQ-004 | `test_graph.py`, `test_gremlin.py` | Shared graph state and fixed primary keys make tests order-dependent. |
| TQ-005 | `test_graph.py`, `test_task.py`, `test_auth.py` | Error assertions inside `except` blocks can pass when no exception occurs. |
| TQ-006 | `test_ollama_embedding.py`, `test_ollama_client.py` | Print-only external checks have no assertions. |
| TQ-007 | `test_faiss_vector_index.py` | Backend abstraction has only Faiss coverage. |

## Missing Coverage Around Core Functions

- `HGraphSession.resolve()` with base URL path prefixes.
- `GraphManager` query filter URL encoding.
- `PropertyKey` advanced builder payload.
- `IndexLabel` multi-field order.
- `Commit2Graph.load_into_graph()` partial-failure behavior.
- `GraphQueryNode` and `VectorQueryNode` dependency failure propagation.
- `VectorQueryNode` top-k and threshold parameter pass-through.
- `LiteLLMEmbedding` factory construction.
- OpenAI/LiteLLM provider failure and streaming contracts.
- `get_embeddings_parallel()` peak concurrency.
- `write_backup_file()` backup artifact contents.

## Tests Reviewed and Accepted

- `hugegraph-python-client/src/tests/api/test_response_validation.py` was run by L2 and passed: `uv run pytest hugegraph-python-client/src/tests/api/test_response_validation.py -q`.
- L5 ran a targeted models/indices test set and reported `52 passed, 3 skipped`.

## Resolved Coverage Gaps

- `CS-001`: `hugegraph-llm/src/tests/api/test_admin_api.py` now covers admin log traversal rejection, absolute-path rejection, insecure default-token rejection, and valid log streaming.
- `CS-002`: client transport and response-validation tests now prove password-like request fields are redacted from debug/error logs.
- `CS-004`: response-validation tests now prove malformed successful JSON raises `ResponseParseError`.
- `CS-008`: Gremlin tests now prove lower-level auth exceptions keep their original type through `GremlinManager.exec()`.
- `CS-013`: extraction-to-commit round-trip tests now prove schema-typed numeric values survive `PropertyGraphExtract.run()` and are accepted by `Commit2Graph`.
- `CS-011`: `/rag` contract tests now prove partial `client_config` only updates explicitly supplied graph settings.
- `CS-012`: config API tests now prove unsupported LLM/reranker providers fail validation before mutating global settings.
- `CS-030`: GraphRAG/RAG/KG integration smoke tests now use production flows/operators instead of test-local pipeline and KG constructor stand-ins.
