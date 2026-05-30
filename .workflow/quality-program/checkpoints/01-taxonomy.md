# G0 Taxonomy Checkpoint

## Files Touched

- `pyproject.toml`
- `docs/quality/test-taxonomy.md`
- `.workflow/quality-program/baseline.md`
- `.workflow/quality-program/checkpoints/01-taxonomy.md`
- `.workflow/quality-program/coverage/client-baseline.json`
- `.workflow/quality-program/coverage/llm-baseline.json`
- Selected deterministic tests under `hugegraph-llm/src/tests/`
- Existing service-bound client tests under `hugegraph-python-client/src/tests/api/`

## Markers Added

- Root pytest markers: `unit`, `contract`, `integration`, `hugegraph`, `smoke`, `external`, `slow`.
- Client deterministic contract tests:
  - `test_auth_routing.py`
  - `test_response_validation.py`
- Client service-bound tests:
  - `test_auth.py`
  - `test_graph.py`
  - `test_graphs.py`
  - `test_gremlin.py`
  - `test_metric.py`
  - `test_schema.py`
  - `test_task.py`
  - `test_traverser.py`
  - `test_variable.py`
  - `test_version.py`
- LLM deterministic `unit` or `contract` tests:
  - API config route contract test
  - config and prompt config tests
  - document and middleware tests
  - selected mocked OpenAI/LiteLLM tests
  - selected LLM operator parser/generation tests

## Commands Run

```bash
uv run pytest hugegraph-python-client/src/tests --collect-only -q
uv run pytest hugegraph-llm/src/tests --collect-only -q
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --collect-only -q
uv run pytest hugegraph-llm/src/tests -m "unit or contract" --collect-only -q
uv run pytest src/tests --collect-only -q
uv run pytest src/tests -m "unit or contract" --collect-only -q
uv sync --extra dev --extra python-client --extra llm
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term --cov-report=json:.workflow/quality-program/coverage/client-baseline.json
uv run pytest src/tests -m "unit or contract" --cov=hugegraph_llm --cov-report=term --cov-report=json:../.workflow/quality-program/coverage/llm-baseline.json
```

## Coverage Baseline

- `pyhugegraph`: 45% line coverage, 15 selected contract tests passed.
- `hugegraph_llm`: 34% line coverage, 101 selected unit/contract tests passed.

## Failures or Skips Observed

- Root-level LLM collection command failed before collection because existing prompt config requires current directory `hugegraph-llm`.
- First coverage attempt failed because `pytest-cov` was not installed in the active `.venv`; `uv sync --extra dev --extra python-client --extra llm` resolved it.
- No unknown marker errors after strict marker config was added.

## Next Goal Readiness

- Ready for G1 service fixture and CI standardization.
- G1 should keep Layer A tests Docker-free and make selected Layer B failures explicit under `HUGEGRAPH_REQUIRED=true`.
