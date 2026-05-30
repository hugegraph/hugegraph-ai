# Quality Program Baseline

## Test Selection Baseline

| Module | Command | Result |
|---|---|---|
| `hugegraph-python-client` all tests collection | `uv run pytest hugegraph-python-client/src/tests --collect-only -q` | 71 collected |
| `hugegraph-python-client` Layer A collection | `uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --collect-only -q` | 15 selected, 56 deselected |
| `hugegraph-llm` all tests collection from repo root | `uv run pytest hugegraph-llm/src/tests --collect-only -q` | failed before collection due existing prompt-config cwd guard |
| `hugegraph-llm` Layer A collection from repo root | `uv run pytest hugegraph-llm/src/tests -m "unit or contract" --collect-only -q` | failed before collection due existing prompt-config cwd guard |
| `hugegraph-llm` all tests collection from module cwd | `uv run pytest src/tests --collect-only -q` | 276 collected |
| `hugegraph-llm` Layer A collection from module cwd | `uv run pytest src/tests -m "unit or contract" --collect-only -q` | 101 selected, 175 deselected |

## Coverage Baseline

| Module | Command | Result | Artifact |
|---|---|---:|---|
| `pyhugegraph` | `uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term --cov-report=json:.workflow/quality-program/coverage/client-baseline.json` | 45% | `.workflow/quality-program/coverage/client-baseline.json` |
| `hugegraph_llm` | `uv run pytest src/tests -m "unit or contract" --cov=hugegraph_llm --cov-report=term --cov-report=json:../.workflow/quality-program/coverage/llm-baseline.json` from `hugegraph-llm/` | 34% | `.workflow/quality-program/coverage/llm-baseline.json` |

## Existing Skips and Service Controls

- `hugegraph-llm/src/tests/conftest.py` now uses `os.environ.setdefault("SKIP_EXTERNAL_SERVICES", "true")`, so selected integration runs can opt in explicitly.
- Client Gremlin tests still support explicit `SKIP_GREMLIN_TESTS=true`.
- LLM provider and external-service tests remain outside the initial `unit or contract` baseline unless they are deterministic mocked contracts.
- Existing `hugegraph-llm` imports can require the current working directory to be `hugegraph-llm`; this is recorded as a baseline command mismatch for later cleanup, not fixed in G0.

## Weak or Unclassified Integration Tests

- `hugegraph-llm/src/tests/integration/test_graph_rag_pipeline.py`
- `hugegraph-llm/src/tests/integration/test_kg_construction.py`
- `hugegraph-llm/src/tests/integration/test_rag_pipeline.py`

These are not reclassified in G0. G5 must inspect whether they import production code, define local replacement pipelines, or only assert mock calls.
