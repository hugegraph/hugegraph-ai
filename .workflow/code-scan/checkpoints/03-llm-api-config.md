# T2 LLM API and Config Checkpoint

Status: completed

## Scope

- `hugegraph-llm/src/hugegraph_llm/api/`
- `hugegraph-llm/src/hugegraph_llm/config/`
- `hugegraph-llm/src/hugegraph_llm/resources/`
- `hugegraph-llm/src/tests/api/`
- `hugegraph-llm/src/tests/config/`

## Findings

- `CS-001`: `/logs` can read arbitrary files through path traversal.
- `CS-009`: config endpoints collapse failures into `Missing Value`.
- `CS-010`: GraphRAG/Text2Gremlin API failures become generic 500s.
- `CS-011`: `client_config` partial requests overwrite global graph settings.
- `CS-012`: unsupported provider types are written into global settings first.
- `CS-020`: runtime prompt YAML and prompt tests have drifted.
- `CS-021`: `.env` sync bypasses Pydantic typing and import has side effects.

## Test-quality Notes

- Added `FIXME:` comments in `admin_api.py`, `test_rag_api.py`,
  `test_prompt_config.py`, and `test_config.py`.
