# T2 LLM Flow and Operator Checkpoint

Status: completed

## Scope

- `hugegraph-llm/src/hugegraph_llm/flows/`
- `hugegraph-llm/src/hugegraph_llm/nodes/`
- `hugegraph-llm/src/hugegraph_llm/operators/`
- `hugegraph-llm/src/hugegraph_llm/state/`
- `hugegraph-llm/src/tests/operators/`
- `hugegraph-llm/src/tests/integration/`

## Findings

- `CS-013`: property graph extraction stringifies values that importer rejects.
- `CS-014`: graph/vector dependency failures are treated as empty retrieval.
- `CS-022`: legacy triples output cannot feed current importer shape.
- `CS-023`: vector recall parameters are lost across flow/node/operator boundary.
- `CS-028`: Text2Gremlin always makes two LLM calls regardless of requested output.

## Test-quality Notes

- Added `FIXME:` comments in property graph, commit-to-graph, vector query,
  GraphRAG/RAG/KG integration, and API tests.
