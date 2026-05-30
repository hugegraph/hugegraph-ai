# Test Matrix

| Layer | Module | Current command | Required services | Current issues | Target command |
|---|---|---|---|---|---|
| Layer A unit/contract | `hugegraph-python-client` | `uv run pytest` from `hugegraph-python-client` | None intended, but current suite is not split | No strict markers yet; unit and integration tests are mixed | `uv run pytest hugegraph-python-client/src/tests -m "unit or contract"` |
| Layer B HugeGraph contract | `hugegraph-python-client` | Same as full client suite | HugeGraph Server `1.7.0` in CI | Service selection not marker-driven | `HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph"` |
| Layer A unit/contract | `hugegraph-llm` | CI selected deterministic directories with `SKIP_EXTERNAL_SERVICES=true` | None | No strict markers yet; global conftest forces external skip | `uv run pytest hugegraph-llm/src/tests -m "unit or contract"` |
| Layer B HugeGraph boundary | `hugegraph-llm` | Integration paths run with `SKIP_EXTERNAL_SERVICES=true` | HugeGraph Server currently `1.5.0` in CI | Uses blind sleep; real boundary selection is unclear | `HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests -m "integration and hugegraph"` |
| Layer C core smoke | `hugegraph-llm` | Existing integration tests | Fake LLM; optional HugeGraph | Need verify production-code imports and avoid replacement pipelines | `uv run pytest hugegraph-llm/src/tests/integration -m "smoke"` |
| Layer D external | `hugegraph-llm` | Skipped by `SKIP_EXTERNAL_SERVICES=true` | Real providers or non-HugeGraph services | Should remain outside default gates | Manual or scheduled workflow with secrets |
