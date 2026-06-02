# Code Scan Issues

Issue IDs use `CS-NNN`. Priorities are P0 highest through P5 lowest.

## Issue Distribution

| Priority | Count |
|---|---:|
| P0 | 1 |
| P1 | 16 |
| P2 | 9 |
| P3 | 3 |
| P4 | 8 |
| P5 | 0 |

## Open Issues

### CS-001: `/logs` can read arbitrary files through path traversal

- Priority: P0
- Module: `hugegraph-llm`
- Layer: API / config / security
- Paths: `hugegraph-llm/src/hugegraph_llm/api/admin_api.py:33`, `hugegraph-llm/src/hugegraph_llm/api/admin_api.py:40`, `hugegraph-llm/src/hugegraph_llm/config/admin_config.py:26`, `hugegraph-llm/src/hugegraph_llm/demo/rag_demo/admin_block.py:27`, `hugegraph-llm/src/hugegraph_llm/demo/rag_demo/app.py:164`
- Status: fixed
- Evidence: `log_file` is accepted from request input and joined with `logs` without basename normalization or allowlist. The injected `log_stream()` opens that path directly. Default auth is disabled and default tokens are predictable.
- Impact: A caller with the default or known admin token can request paths outside `logs/`, exposing any readable file from the service process.
- Fix: `admin_http_api` now rejects unset/default admin tokens, rejects absolute paths, drive-qualified paths, path separators, and traversal values before calling `log_stream()`.
- Test note: Added `test_admin_api.py` coverage for traversal rejection, absolute-path rejection, default-token rejection, and valid log streaming under `logs/`.

### CS-002: Client request/error logs can leak auth secrets

- Priority: P1
- Module: `hugegraph-python-client`
- Layer: transport / auth
- Paths: `hugegraph-python-client/src/pyhugegraph/utils/huge_requests.py:145`, `hugegraph-python-client/src/pyhugegraph/utils/util.py:120`, `hugegraph-python-client/src/pyhugegraph/api/auth.py:43`, `hugegraph-python-client/src/pyhugegraph/api/auth.py:68`
- Status: fixed
- Evidence: `HGraphSession.request()` logs raw `kwargs`, and `ResponseValidation` logs raw `response.request.body` on HTTP errors. Auth user create/modify requests serialize `user_password` into the request body.
- Impact: Passwords can enter debug/error logs during auth failures or debug tracing.
- Fix: `HGraphSession.request()` and `ResponseValidation` now redact password/token/secret/auth-like fields before logging request kwargs or error request bodies.
- Test note: Added contract coverage proving auth request passwords do not appear in debug/error logs.

### CS-003: Absolute API paths drop configured URL path prefixes

- Priority: P1
- Module: `hugegraph-python-client`
- Layer: transport / routing
- Paths: `hugegraph-python-client/src/pyhugegraph/utils/huge_requests.py:100`, `hugegraph-python-client/src/pyhugegraph/utils/huge_requests.py:120`, `hugegraph-python-client/src/pyhugegraph/api/auth.py:37`, `hugegraph-python-client/src/pyhugegraph/api/auth.py:84`
- Status: open
- Evidence: `HGraphSession.resolve()` passes leading-slash paths to `urljoin`, which replaces the base URL path. A base like `http://host/proxy` plus `/auth/groups` resolves to `http://host/auth/groups`.
- Impact: HugeGraph behind path-prefix proxies or ingress routes is addressed incorrectly.
- Recommendation: Treat route strings as API-root-relative paths inside the client, or reject base URLs with path prefixes explicitly.
- Test note: Added a `FIXME:` in `test_auth_routing.py` because current dummy routing duplicates the production resolver and misses this.

### CS-004: Successful response parse failures are swallowed as empty success

- Priority: P1
- Module: `hugegraph-python-client`
- Layer: transport / response validation
- Paths: `hugegraph-python-client/src/pyhugegraph/utils/util.py:85`, `hugegraph-python-client/src/pyhugegraph/utils/util.py:136`
- Status: fixed
- Evidence: `ResponseValidation.__call__()` catches broad `Exception` after successful HTTP parsing and returns the default `{}`. A `200 OK` response with malformed JSON becomes an empty dict.
- Impact: Protocol drift or corrupt responses are indistinguishable from legitimate empty results.
- Fix: successful-response parse failures now raise `ResponseParseError` instead of returning `{}`.
- Test note: Added malformed `2xx` JSON coverage in `test_response_validation.py`.

### CS-005: Graphspace support depends on one fragile constructor-time probe

- Priority: P1
- Module: `hugegraph-python-client`
- Layer: transport / routing
- Paths: `hugegraph-python-client/src/pyhugegraph/utils/huge_config.py:44`, `hugegraph-python-client/src/pyhugegraph/utils/huge_config.py:73`, `hugegraph-python-client/src/pyhugegraph/utils/huge_router.py:139`
- Status: open
- Evidence: `HGraphConfig.__post_init__()` probes `/versions` with a fixed `0.5s` timeout. Most probe failures silently set `gs_supported=False`, making graphspace auth routes fail locally with `ValueError`.
- Impact: HugeGraph 1.7+ auth behavior becomes sensitive to a single transient version probe.
- Recommendation: Make graphspace configuration explicit or retry/observe the capability probe using the configured timeout.
- Test note: Current routing tests do not cover probe failure and graphspace fallback behavior.

### CS-006: Graph query APIs build query strings without URL encoding

- Priority: P1
- Module: `hugegraph-python-client`
- Layer: client-api
- Paths: `hugegraph-python-client/src/pyhugegraph/api/graph.py:68`, `hugegraph-python-client/src/pyhugegraph/api/graph.py:73`, `hugegraph-python-client/src/pyhugegraph/api/graph.py:173`, `hugegraph-python-client/src/pyhugegraph/utils/huge_requests.py:144`
- Status: open
- Evidence: `getVertexByPage()`, `getVertexByCondition()`, and `getEdgeByPage()` concatenate labels and JSON properties directly into the URL.
- Impact: Property values containing `&`, `?`, `#`, `=`, or spaces can corrupt filters and query different data.
- Recommendation: Use `params=` or `urllib.parse.urlencode()` for all query parameters.
- Test note: Added a `FIXME:` in `test_graph.py` for pagination/filter contract coverage.

### CS-007: `PropertyKey` builder drops advertised `calc*()` and `userdata()`

- Priority: P1
- Module: `hugegraph-python-client`
- Layer: schema
- Paths: `hugegraph-python-client/src/pyhugegraph/api/schema_manage/property_key.py:96`, `hugegraph-python-client/src/pyhugegraph/api/schema_manage/property_key.py:117`, `hugegraph-python-client/src/pyhugegraph/api/schema_manage/property_key.py:135`, `hugegraph-python-client/src/pyhugegraph/api/schema_manage/property_key.py:144`
- Status: open
- Evidence: Builder methods set aggregate/userdata state, but `create()` serializes only name, data type, and cardinality.
- Impact: Callers believe they created aggregate/userdata property keys, but the server never receives those fields.
- Recommendation: Include these fields in the create payload or remove/disable unsupported mutators.
- Test note: Added a `FIXME:` in `test_schema.py`.

### CS-008: Gremlin API rewrites all failures as `NotFoundError`

- Priority: P1
- Module: `hugegraph-python-client`
- Layer: gremlin / error contract
- Paths: `hugegraph-python-client/src/pyhugegraph/api/gremlin.py:48`, `hugegraph-python-client/src/pyhugegraph/api/gremlin.py:54`, `hugegraph-python-client/src/tests/api/test_gremlin.py:99`
- Status: fixed
- Evidence: `GremlinManager.exec()` catches every exception and raises `NotFoundError`.
- Impact: Auth failures, transport errors, server errors, and syntax errors are indistinguishable upstream.
- Fix: `GremlinManager.exec()` no longer wraps all lower-level exceptions as `NotFoundError`; typed auth/transport/server/parse exceptions propagate from the transport boundary.
- Test note: Added unit coverage proving `NotAuthorizedError` is preserved through `GremlinManager.exec()`.

### CS-009: Config endpoints collapse all failures into `Missing Value`

- Priority: P1
- Module: `hugegraph-llm`
- Layer: API
- Paths: `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:155`, `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:198`, `hugegraph-llm/src/hugegraph_llm/api/exceptions/rag_exceptions.py:33`
- Status: open
- Evidence: `/config/graph`, `/config/llm`, `/config/embedding`, and `/config/rerank` construct `RAGResponse(status_code=res, message="Missing Value")` for all non-success cases.
- Impact: Connection, auth, unsupported provider, and validation failures become the same client-visible message.
- Recommendation: Return structured failure details from config application and map them to accurate HTTP details.
- Test note: Added a `FIXME:` in `test_rag_api.py`.

### CS-010: GraphRAG/Text2Gremlin API failures are flattened into generic 500s

- Priority: P1
- Module: `hugegraph-llm`
- Layer: API / test-quality
- Paths: `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:145`, `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:224`, `hugegraph-llm/src/tests/api/test_rag_api.py:164`
- Status: open
- Evidence: Broad `Exception` handlers return one generic detail string; the test suite asserts this behavior for `text2gremlin`.
- Impact: Provider, graph, schema, prompt, and internal errors cannot be distinguished by API callers.
- Recommendation: Preserve stable response shape but expose actionable failure categories.
- Test note: Added a `FIXME:` in `test_rag_api.py`.

### CS-011: `client_config` partial requests overwrite global graph config

- Priority: P1
- Module: `hugegraph-llm`
- Layer: API / models / config
- Paths: `hugegraph-llm/src/hugegraph_llm/api/models/rag_requests.py:27`, `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:92`
- Status: fixed
- Evidence: `GraphConfigRequest` has concrete defaults and `set_graph_config()` writes every field to global `huge_settings` whenever `client_config` exists.
- Impact: A request intended to override one field can clear credentials, graph name, or graphspace for the whole process.
- Fix: request-scoped graph config updates now use `model_fields_set`, so only explicitly provided nested fields mutate `huge_settings`.
- Test note: Added `/rag` contract coverage proving partial `client_config` updates only the supplied graph fields.

### CS-012: Unsupported provider types are written into global settings before validation

- Priority: P1
- Module: `hugegraph-llm`
- Layer: API / models / config
- Paths: `hugegraph-llm/src/hugegraph_llm/api/models/rag_requests.py:106`, `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:163`, `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:188`, `hugegraph-llm/src/hugegraph_llm/config/llm_config.py:29`
- Status: fixed
- Evidence: Request models use bare `str` for `llm_type` and `reranker_type`; handlers write values to global settings before branch validation.
- Impact: One bad request can poison process-global provider state for subsequent requests.
- Fix: LLM and reranker request models now validate provider types with `Literal`, causing unsupported providers to fail with `422` before handler-side global mutation.
- Test note: Added config API coverage proving unsupported provider requests do not call apply callbacks or mutate global provider settings.

### CS-013: Property graph extraction stringifies values that importer rejects

- Priority: P1
- Module: `hugegraph-llm`
- Layer: LLM operator / graph import
- Paths: `hugegraph-llm/src/hugegraph_llm/operators/llm_op/property_graph_extract.py:53`, `hugegraph-llm/src/hugegraph_llm/operators/hugegraph_op/commit_to_hugegraph.py:134`, `hugegraph-llm/src/hugegraph_llm/flows/import_graph_data.py:65`
- Status: fixed
- Evidence: `filter_item()` converts non-string properties to strings, while `Commit2Graph` enforces schema Python types and skips mismatches. Edge writes can continue and the flow reports success.
- Impact: KG import can partially fail while the UI reports success.
- Fix: `filter_item()` no longer stringifies non-string property values, so extracted JSON numeric values survive into `Commit2Graph` schema validation.
- Test note: Added extraction-to-commit round-trip coverage proving `PropertyGraphExtract.run()` preserves typed values accepted by `Commit2Graph`.

### CS-014: Graph/vector dependency failures are treated as empty retrieval

- Priority: P1
- Module: `hugegraph-llm`
- Layer: nodes / operators
- Paths: `hugegraph-llm/src/hugegraph_llm/nodes/hugegraph_node/gremlin_execute.py:50`, `hugegraph-llm/src/hugegraph_llm/nodes/hugegraph_node/graph_query_node.py:152`, `hugegraph-llm/src/hugegraph_llm/nodes/hugegraph_node/graph_query_node.py:423`, `hugegraph-llm/src/hugegraph_llm/nodes/index_node/vector_query_node.py:58`
- Status: open
- Evidence: HugeGraph and vector exceptions are converted to strings, empty lists, or original context.
- Impact: Answer synthesis can proceed as if retrieval found no evidence, producing misleading answers.
- Recommendation: Add structured failure fields and fail fast by default; allow fallback only via explicit mode.
- Test note: Covered by `FIXME:` comments in integration and vector-query tests.

### CS-015: LiteLLM embedding factory crashes for supported config

- Priority: P1
- Module: `hugegraph-llm`
- Layer: model provider
- Paths: `hugegraph-llm/src/hugegraph_llm/models/embeddings/init_embedding.py:44`, `hugegraph-llm/src/hugegraph_llm/models/embeddings/litellm.py:30`, `hugegraph-llm/src/hugegraph_llm/config/llm_config.py:32`
- Status: open
- Evidence: `get_embedding()` supports `embedding_type == "litellm"` but constructs `LiteLLMEmbedding` without required `embedding_dimension`.
- Impact: Config-driven LiteLLM embedding initialization fails before retrieval/indexing starts.
- Recommendation: Align factory and class constructor contracts.
- Test note: Added provider factory gap to the test-quality ledger.

### CS-016: OpenAI wrapper returns provider failures as ordinary model text

- Priority: P1
- Module: `hugegraph-llm`
- Layer: LLM provider
- Paths: `hugegraph-llm/src/hugegraph_llm/models/llms/openai.py:78`, `hugegraph-llm/src/hugegraph_llm/models/llms/openai.py:116`, `hugegraph-llm/src/hugegraph_llm/models/llms/openai.py:168`, `hugegraph-llm/src/hugegraph_llm/models/llms/openai.py:209`, `hugegraph-llm/src/tests/models/llms/test_openai_client.py:254`
- Status: open
- Evidence: Bad request/auth exceptions are returned or yielded as `"Error: ..."` strings.
- Impact: Flows can treat provider outages as valid LLM output.
- Recommendation: Raise typed provider exceptions and map them at API/flow boundaries.
- Test note: Added a `FIXME:` in `test_openai_client.py`.

### CS-017: Embedding dimension probing hides real provider failures

- Priority: P1
- Module: `hugegraph-llm`
- Layer: embedding provider / vector index
- Paths: `hugegraph-llm/src/hugegraph_llm/models/embeddings/init_embedding.py:68`, `hugegraph-llm/src/hugegraph_llm/models/embeddings/init_embedding.py:82`, `hugegraph-llm/src/hugegraph_llm/models/embeddings/init_embedding.py:98`
- Status: open
- Evidence: Provider probe exceptions are broadly caught and fallback dimensions are silently retained.
- Impact: Auth/network/provider errors can create or reuse vector stores with wrong dimensions.
- Recommendation: Surface probe failures unless a dimension was explicitly configured and validated.
- Test note: No current factory tests cover probe failure.

### CS-018: `IndexLabel.by()` loses compound-index field order

- Priority: P2
- Module: `hugegraph-python-client`
- Layer: schema
- Paths: `hugegraph-python-client/src/pyhugegraph/api/schema_manage/index_label.py:42`, `hugegraph-python-client/src/pyhugegraph/api/schema_manage/index_label.py:47`, `hugegraph-python-client/src/pyhugegraph/api/schema_manage/index_label.py:90`
- Status: open
- Evidence: Fields are stored in a `set`, then converted back to `list`.
- Impact: Compound index field order and duplicate handling become non-deterministic.
- Recommendation: Store ordered input, with explicit ordered de-duplication if needed.
- Test note: Added a `FIXME:` in `test_schema.py`.

### CS-019: `getVertexByCondition()` accepts `page` but drops next-page token

- Priority: P2
- Module: `hugegraph-python-client`
- Layer: client-api
- Paths: `hugegraph-python-client/src/pyhugegraph/api/graph.py:86`, `hugegraph-python-client/src/pyhugegraph/api/graph.py:95`, `hugegraph-python-client/src/pyhugegraph/api/graph.py:100`
- Status: open
- Evidence: Method takes `page` and sends it, but returns only `list[VertexData]`; sibling `getVertexByPage()` returns `(items, next_page)`.
- Impact: Callers cannot page through condition queries.
- Recommendation: Return `(items, next_page)` or remove the `page` parameter.
- Test note: No multi-page condition query test exists.

### CS-020: Runtime prompt YAML and prompt tests have drifted

- Priority: P2
- Module: `hugegraph-llm`
- Layer: config / prompt
- Paths: `hugegraph-llm/src/hugegraph_llm/config/models/base_prompt_config.py:55`, `hugegraph-llm/src/hugegraph_llm/config/prompt_config.py:267`, `hugegraph-llm/src/hugegraph_llm/resources/demo/config_prompt.yaml:51`, `hugegraph-llm/src/hugegraph_llm/api/models/rag_requests.py:61`
- Status: open
- Evidence: Runtime prompts load from YAML, but tests focus on class constants and fixture examples. Request model defaults also freeze prompt strings at import time.
- Impact: Passing prompt tests do not prove runtime prompt contracts or language-specific YAML behavior.
- Recommendation: Validate runtime-loaded YAML prompt schema/version and resolve defaults at request handling time.
- Test note: Added `FIXME:` comments in prompt tests.

### CS-021: `.env` sync bypasses Pydantic typing and import has side effects

- Priority: P2
- Module: `hugegraph-llm`
- Layer: config
- Paths: `hugegraph-llm/src/hugegraph_llm/config/models/base_config.py:95`, `hugegraph-llm/src/hugegraph_llm/config/models/base_config.py:125`, `hugegraph-llm/src/hugegraph_llm/config/__init__.py:29`
- Status: open
- Evidence: `_sync_env_to_object()` writes raw strings with `setattr`; config import can mutate `os.environ` and create/sync `.env`.
- Impact: Typed fields can become strings and imports are not side-effect free.
- Recommendation: Rebuild/validate settings through Pydantic and move disk/env mutation to explicit initialization.
- Test note: Added a `FIXME:` in `test_config.py`.

### CS-022: Legacy triples output cannot feed current importer shape

- Priority: P2
- Module: `hugegraph-llm`
- Layer: LLM operator / graph import
- Paths: `hugegraph-llm/src/hugegraph_llm/operators/llm_op/info_extract.py:94`, `hugegraph-llm/src/hugegraph_llm/operators/hugegraph_op/commit_to_hugegraph.py:171`
- Status: open
- Evidence: Triples extraction emits `start/end/type`; importer expects `outV/inV/label`.
- Impact: A supported-looking KG extraction mode cannot be imported without an undocumented adapter.
- Recommendation: Add a formal adapter or explicitly deprecate/directly reject this path.
- Test note: No bridge contract test exists.

### CS-023: Vector recall parameters are lost across flow/node/operator boundaries

- Priority: P2
- Module: `hugegraph-llm`
- Layer: flow / node / operator
- Paths: `hugegraph-llm/src/hugegraph_llm/flows/rag_flow_vector_only.py:55`, `hugegraph-llm/src/hugegraph_llm/flows/rag_flow_graph_vector.py:64`, `hugegraph-llm/src/hugegraph_llm/nodes/index_node/vector_query_node.py:42`, `hugegraph-llm/src/hugegraph_llm/operators/index_op/vector_index_query.py:33`
- Status: open
- Evidence: Flows record `topk_return_results` and `vector_dis_threshold`, but node/operator default to `max_items=3` and hard-coded `dis_threshold=2`.
- Impact: API/flow config does not control actual vector retrieval.
- Recommendation: Thread the parameters through one explicit contract and test the flow boundary.
- Test note: Added a `FIXME:` in `test_vector_index_query.py`.

### CS-024: LiteLLM sync streaming violates `BaseLLM` streaming contract

- Priority: P2
- Module: `hugegraph-llm`
- Layer: LLM provider
- Paths: `hugegraph-llm/src/hugegraph_llm/models/llms/base.py:42`, `hugegraph-llm/src/hugegraph_llm/models/llms/litellm.py:111`
- Status: open
- Evidence: Base contract is generator-of-strings, but LiteLLM sync streaming accumulates and returns a plain string while callback payloads differ.
- Impact: Provider swaps can silently break streaming consumers.
- Recommendation: Yield normalized token strings incrementally.
- Test note: No provider streaming contract test exists.

### CS-025: One `dis_threshold` abstraction has incompatible backend semantics

- Priority: P2
- Module: `hugegraph-llm`
- Layer: vector index
- Paths: `hugegraph-llm/src/hugegraph_llm/indices/vector_index/base.py:59`, `hugegraph-llm/src/hugegraph_llm/indices/vector_index/faiss_vector_store.py:76`, `hugegraph-llm/src/hugegraph_llm/indices/vector_index/milvus_vector_store.py:156`, `hugegraph-llm/src/hugegraph_llm/indices/vector_index/qdrant_vector_store.py:57`
- Status: open
- Evidence: Faiss/Milvus use raw L2 distance; Qdrant uses cosine similarity converted to `1 - score`.
- Impact: Same config returns different accept/reject behavior per backend.
- Recommendation: Normalize scoring at the boundary or expose backend-specific threshold types.
- Test note: Added a `FIXME:` in Faiss vector index tests.

### CS-026: Graph backup can report success with empty `schema.json`

- Priority: P2
- Module: `hugegraph-llm`
- Layer: utility / backup
- Paths: `hugegraph-llm/src/hugegraph_llm/utils/hugegraph_utils.py:112`, `hugegraph-llm/src/hugegraph_llm/utils/hugegraph_utils.py:147`
- Status: open
- Evidence: `backup_data()` opens `schema.json`, but `write_backup_file()` writes only a `.groovy` sibling when the payload contains `"schema"`.
- Impact: Backup output can be incomplete while returning success.
- Recommendation: Write both expected artifacts or name the groovy-only artifact accurately.
- Test note: No focused backup artifact test exists.

### CS-027: `PyHugeClient` creates independent sessions per manager

- Priority: P3
- Module: `hugegraph-python-client`
- Layer: transport / lifecycle
- Paths: `hugegraph-python-client/src/pyhugegraph/client.py:40`, `hugegraph-python-client/src/pyhugegraph/client.py:61`, `hugegraph-python-client/src/pyhugegraph/api/common.py:51`
- Status: open
- Evidence: `manager_builder` constructs a new `HGraphSession` for each lazily created manager and `PyHugeClient` has no unified `close()`.
- Impact: Long-lived clients can retain multiple sessions/adapters and leak resources.
- Recommendation: Share one session per client and expose `close()` / context manager support.
- Test note: No lifecycle test exists.

### CS-028: Text2Gremlin always makes two LLM calls regardless of requested outputs

- Priority: P3
- Module: `hugegraph-llm`
- Layer: flow / LLM operator / performance
- Paths: `hugegraph-llm/src/hugegraph_llm/flows/text2gremlin.py:50`, `hugegraph-llm/src/hugegraph_llm/operators/llm_op/gremlin_generate.py:69`, `hugegraph-llm/src/hugegraph_llm/flows/text2gremlin.py:107`
- Status: open
- Evidence: `requested_outputs` filters returned fields, but `GremlinGenerateSynthesize` always calls raw and initialized prompts.
- Impact: Unnecessary latency and token cost for callers requesting only one Gremlin output.
- Recommendation: Let requested outputs drive the execution plan.
- Test note: No call-count/cost contract test exists.

### CS-029: `get_embeddings_parallel()` launches all batches concurrently

- Priority: P3
- Module: `hugegraph-llm`
- Layer: embedding utility / performance
- Paths: `hugegraph-llm/src/hugegraph_llm/utils/embedding_utils.py:36`, `hugegraph-llm/src/hugegraph_llm/utils/embedding_utils.py:53`
- Status: open
- Evidence: The docstring claims semaphore-based concurrency, but implementation creates one task per batch and gathers them all.
- Impact: Large indexing jobs can burst into many provider calls and hit rate/memory/socket limits.
- Recommendation: Add real bounded concurrency with configurable worker count.
- Test note: No peak-concurrency test exists.

### CS-030: Integration tests reimplement production flows locally

- Priority: P4
- Module: `hugegraph-llm`
- Layer: test-quality
- Paths: `hugegraph-llm/src/tests/integration/test_graph_rag_pipeline.py:39`, `hugegraph-llm/src/tests/integration/test_rag_pipeline.py:33`, `hugegraph-llm/src/tests/integration/test_kg_construction.py:46`
- Status: fixed
- Evidence: Tests defined local `RAGPipeline`, local document/vector/LLM classes, and local `KGConstructor`.
- Impact: Green integration tests did not validate production flow wiring.
- Fix: Replaced the local stand-ins with production `RAGVectorOnlyFlow`, `ChunkSplitter`, vector index operators, `GraphExtractFlow`, and `PropertyGraphExtract` smoke tests using deterministic test doubles only at external boundaries.
- Test note: Removed the resolved `FIXME:` comments and verified the three integration smoke files directly.

### CS-031: Commit2Graph tests mock away core branch behavior

- Priority: P4
- Module: `hugegraph-llm`
- Layer: test-quality
- Paths: `hugegraph-llm/src/tests/operators/hugegraph_op/test_commit_to_hugegraph.py:117`, `hugegraph-llm/src/tests/operators/hugegraph_op/test_commit_to_hugegraph_load_into_graph.py:72`
- Status: open
- Evidence: Tests patch `init_schema_if_need`, `load_into_graph`, `_handle_graph_creation`, or `_create_property` while claiming to cover graph loading behavior.
- Impact: Core import failure modes are not tested.
- Recommendation: Add contract tests that exercise real branch logic with a test service or focused fake client.
- Test note: Added `FIXME:` comments in commit tests.

### CS-032: Main `/rag` and `/rag/graph` success contracts are untested

- Priority: P4
- Module: `hugegraph-llm`
- Layer: test-quality
- Paths: `hugegraph-llm/src/tests/api/test_rag_api.py:47`, `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:59`, `hugegraph-llm/src/hugegraph_llm/api/rag_api.py:126`
- Status: open
- Evidence: API tests cover config endpoints, one validation error, and one `text2gremlin` failure, not success response shaping.
- Impact: Response filtering and graph recall shape can drift unnoticed.
- Recommendation: Add happy-path HTTP contract tests.
- Test note: Added a `FIXME:` in `test_rag_api.py`.

### CS-033: Shared HugeGraph fixtures still runtime-skip selected integration tests

- Priority: P4
- Module: cross-module
- Layer: test-quality
- Paths: `hugegraph-llm/src/tests/fixtures/hugegraph_service.py:71`, `hugegraph-python-client/src/tests/fixtures/hugegraph_service.py:71`, `docs/quality/test-taxonomy.md:31`
- Status: open
- Evidence: Fixture calls `pytest.skip()` when service is absent and `HUGEGRAPH_REQUIRED` is false, conflicting with the selected Layer B semantics.
- Impact: Selected integration tests can silently disappear.
- Recommendation: Prefer explicit deselection or required-service failure semantics for selected integration gates.
- Test note: Recorded in test-quality ledger.

### CS-034: Client error tests are false-green

- Priority: P4
- Module: `hugegraph-python-client`
- Layer: test-quality
- Paths: `hugegraph-python-client/src/tests/api/test_graph.py:87`, `hugegraph-python-client/src/tests/api/test_graph.py:143`, `hugegraph-python-client/src/tests/api/test_task.py:52`, `hugegraph-python-client/src/tests/api/test_auth.py:85`
- Status: open
- Evidence: Several tests assert only inside `except` blocks and do not fail when no exception is raised.
- Impact: Error-surfacing regressions can pass.
- Recommendation: Use `pytest.raises` / `assertRaises`.
- Test note: Recorded in test-quality ledger.

### CS-035: Client graph/gremlin integration tests share dirty graph state

- Priority: P4
- Module: `hugegraph-python-client`
- Layer: test-quality
- Paths: `hugegraph-python-client/src/tests/api/test_graph.py:33`, `hugegraph-python-client/src/tests/api/test_gremlin.py:58`, `hugegraph-python-client/src/tests/client_utils.py:104`
- Status: open
- Evidence: Tests insert fixed primary-key data and rely on class-level or previous-test cleanup.
- Impact: Assertions become order-dependent and flaky.
- Recommendation: Clear/reseed per test or move to function-scoped isolated fixtures.
- Test note: Added `FIXME:` comments in graph and gremlin tests.

### CS-036: `GraphsManager.clear_graph_all_data()` version branch lacks direct coverage

- Priority: P4
- Module: `hugegraph-python-client`
- Layer: test-quality
- Paths: `hugegraph-python-client/src/pyhugegraph/api/graphs.py:38`, `hugegraph-python-client/src/tests/api/test_graphs.py:50`
- Status: open
- Evidence: The implementation switches between destructive DELETE and graphspace-aware PUT, but tests only perform weak unrelated smoke assertions.
- Impact: Destructive clear semantics can drift without focused coverage.
- Recommendation: Add routing contract tests for legacy and graphspace paths.
- Test note: Recorded in test-quality ledger.

### CS-037: Provider/backend tests miss contract drift

- Priority: P4
- Module: `hugegraph-llm`
- Layer: test-quality
- Paths: `hugegraph-llm/src/tests/models/embeddings/test_ollama_embedding.py:35`, `hugegraph-llm/src/tests/models/llms/test_ollama_client.py:29`, `hugegraph-llm/src/tests/indices/test_faiss_vector_index.py:42`
- Status: open
- Evidence: Some opt-in external tests print without assertions, and vector backend coverage is Faiss-only.
- Impact: LiteLLM factory, provider streaming, Qdrant/Milvus threshold semantics, and bounded embedding concurrency are not protected.
- Recommendation: Add deterministic provider/backend contract tests using fakes/mocks.
- Test note: Added a `FIXME:` in Faiss tests and recorded provider gaps.

## Fixed Style-only Issues

None. No style-only source fixes were needed during this scan.

## Deferred or Duplicate Issues

- L6 duplicate of CS-030: GraphRAG/RAG/KG test-local fake integration coverage.
- L6 duplicate of CS-031: Commit2Graph helper patching masks real import behavior.
- L2 duplicate of CS-035: client graph/gremlin shared state flakiness.
- L4 duplicate of CS-014: GraphRAG dependency failures hidden by empty/fallback results.
