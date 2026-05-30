# P0 Preflight Checkpoint

## Repository State

- Branch: `goal-test`
- Start SHA: `d048bc9fa07042833549dd1def5ff3222c47be70`
- Dirty files before P0 edits: none
- Workspace: Python `uv` workspace.
- Ownership: `hugegraph-llm/` is the highest-risk module; `hugegraph-python-client/` is the lower-level HugeGraph boundary dependency.
- Workflow rule: research-first, staged execution, explicit checkpoints.

## Open PR Collision Quarantine

Snapshot time: `2026-05-30T17:18:30Z`

| PR | Head | Mergeable | Files | Collision surface |
|---:|---|---|---:|---|
| #350 | `yaml-config-migration` | MERGEABLE | 16 | Config migration; deferred boundary. |
| #342 | `fix/backend-metrics-strict-assertion` | MERGEABLE | 1 | Python-client targeted test fix; inspect before touching related client metrics tests. |
| #329 | `fix/number_type_vertex_id` | MERGEABLE | 7 | Python-client vertex ID behavior; quarantine for G2 ID tests/fixes. |
| #323 | `fix-gremlin-example-empty-list` | MERGEABLE | 3 | LLM Gremlin example index behavior; quarantine for G4/G5 Gremlin tests. |
| #315 | `flow_test` | MERGEABLE | 3 | Flow integration tests; avoid flow redesign and inspect before G5. |
| #277 | `yaml_config` | CONFLICTING | 5 | YAML config migration; deferred boundary. |
| #240 | `property_embedding` | CONFLICTING | 53 | Vector/property embedding and client/LLM surface; deferred boundary. |
| #222 | `auto_test_llms` | CONFLICTING | 5 | LLM auto-test/provider surface; avoid real provider credential expansion. |
| #179 | `main` | CONFLICTING | 8 | Async/streaming API refactor; deferred boundary. |
| #92 | `ragas` | CONFLICTING | 9 | RAG evaluation surface; outside default scope. |

## Current CI Workflows

- `.github/workflows/hugegraph-python-client.yml`
  - Single `build` job for Python `3.10`, `3.11`, `3.12`.
  - Starts `hugegraph/hugegraph:1.7.0` as a GitHub Actions service.
  - Uses `/versions` health check with five retries.
  - Runs the example script and then `uv run pytest` from `hugegraph-python-client`.
- `.github/workflows/hugegraph-llm.yml`
  - Single `build` job for Python `3.10`, `3.11`.
  - Starts HugeGraph manually with `docker run ... hugegraph/hugegraph:1.5.0`.
  - Uses blind `sleep 10` readiness.
  - Runs unit and integration paths with `SKIP_EXTERNAL_SERVICES=true`.
- `.github/workflows/ruff.yml`
  - Existing style/lint gate.

## Current Test Layout

- Client tests live under `hugegraph-python-client/src/tests/api/`.
- LLM deterministic tests live under `hugegraph-llm/src/tests/config/`, `document/`, `middleware/`, `operators/`, `models/`, `indices/`, and `api/`.
- LLM integration tests currently include:
  - `hugegraph-llm/src/tests/integration/test_graph_rag_pipeline.py`
  - `hugegraph-llm/src/tests/integration/test_kg_construction.py`
  - `hugegraph-llm/src/tests/integration/test_rag_pipeline.py`
- Root `pyproject.toml` has no `[tool.pytest.ini_options]` marker definitions yet.

## Current Skip and Service Controls

- `hugegraph-llm/src/tests/conftest.py` forces `SKIP_EXTERNAL_SERVICES=true` globally.
- LLM external tests use `SKIP_EXTERNAL_SERVICES` to skip provider/service checks.
- Client Gremlin tests support explicit `SKIP_GREMLIN_TESTS=true`.
- Client CI already uses HugeGraph `1.7.0`; LLM CI still uses `1.5.0`.
- Existing service readiness is inconsistent: client CI uses health checks, LLM CI uses `sleep 10`.

## Abort Conditions Found

- No dirty working-tree files before P0 edits.
- No production files edited during P0.
- Collision risk exists for client vertex ID behavior (#329), LLM Gremlin example behavior (#323), flow integration (#315), YAML config (#350/#277), vector/property embedding (#240), and async/streaming API (#179). These are quarantined for later goals.

## Next Goal Readiness

- Ready for G0 taxonomy and baseline work.
- First G0 edits should be limited to pytest marker definitions, test taxonomy docs, file-level markers, LLM conftest skip semantics, baseline artifacts, and checkpoint updates.
