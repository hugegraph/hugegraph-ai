# Service Matrix

| Service | Default version | Used by | Health check | Required env | Failure behavior |
|---|---|---|---|---|---|
| HugeGraph Server | `hugegraph/hugegraph:1.7.0` | Layer B, Layer C graph-boundary smoke | `GET /versions` | `HUGEGRAPH_URL`, `HUGEGRAPH_REQUIRED` | fail if selected and required |
| LLM providers | explicit user/provider config only | Layer D only | provider SDK call | provider-specific API keys | excluded from default gates |
| Embedding/reranker/vector DB providers | explicit user/provider config only | Layer D only unless deterministic fake | provider-specific | provider-specific credentials | excluded from default gates |
