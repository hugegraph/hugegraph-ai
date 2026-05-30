# G1 Service Fixture Checkpoint

## Files Touched

- `hugegraph-python-client/src/tests/fixtures/hugegraph_service.py`
- `hugegraph-python-client/src/tests/fixtures/__init__.py`
- `hugegraph-python-client/src/tests/conftest.py`
- `hugegraph-python-client/src/tests/client_utils.py`
- `hugegraph-llm/src/tests/fixtures/hugegraph_service.py`
- `hugegraph-llm/src/tests/fixtures/__init__.py`
- `hugegraph-llm/src/tests/conftest.py`
- `.github/workflows/hugegraph-python-client.yml`
- `.github/workflows/hugegraph-llm.yml`
- `docs/quality/hugegraph-integration.md`

## Harness Changes

- Added explicit `HugeGraphService` env contract helpers for client and LLM tests.
- Added `HUGEGRAPH_REQUIRED=true` behavior: selected service tests fail if `/versions` is unavailable after the retry budget.
- Preserved local opt-out semantics: when `HUGEGRAPH_REQUIRED=false`, selected integration tests may skip if no local service is running.
- Adapted `ClientUtils(service=...)` so future client contract tests can use fixture-provided URL, graph, auth, and graphspace values.

## CI Changes

- Replaced LLM CI manual `docker run ... hugegraph/hugegraph:1.5.0` plus `sleep 10` with a GitHub Actions service using `hugegraph/hugegraph:1.7.0`.
- Added `/versions` health check for LLM CI with eight retries.
- Added explicit `HUGEGRAPH_REQUIRED`, `HUGEGRAPH_URL`, `HUGEGRAPH_GRAPH`, `HUGEGRAPH_USER`, and `HUGEGRAPH_PASSWORD` env to selected integration jobs.
- Client CI already used HugeGraph `1.7.0`; G1 adds explicit HugeGraph env to its pytest step.

## Commands Run

```bash
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
uv run pytest src/tests -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" --collect-only -q
HUGEGRAPH_REQUIRED=true uv run pytest src/tests -m "integration and hugegraph" --collect-only -q
uv run ruff format --check hugegraph-python-client/src/tests hugegraph-llm/src/tests
uv run ruff check hugegraph-python-client/src/tests hugegraph-llm/src/tests
git diff --check
uv run python -c "import yaml, pathlib; [yaml.safe_load(pathlib.Path(p).read_text()) for p in ['.github/workflows/hugegraph-llm.yml','.github/workflows/hugegraph-python-client.yml']]"
```

## Results

- Client Layer A: 15 passed, 56 deselected.
- LLM Layer A: 101 passed, 175 deselected.
- Client Layer B collection: 56 selected, 15 deselected.
- LLM Layer B collection: no tests selected yet; pytest returned exit code 5. This is classified as a current coverage gap to be filled by G3, not a service setup failure.
- Ruff format and lint checks passed for touched test files.
- Workflow YAML parsed successfully with PyYAML.

## Failures or Skips

- No selected unit/contract test requires Docker.
- LLM `integration and hugegraph` selection is empty before G3 adds real-boundary tests.

## Next Goal Readiness

- Ready for G2 pyhugegraph contract hardening.
- G2 should convert client integration tests to consume `hugegraph_service` and should run real HugeGraph tests only with `HUGEGRAPH_REQUIRED=true`.
