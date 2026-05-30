# G6 Coverage Ratchet Checkpoint

## Status

Complete.

## CI Split

Client workflow:

| Job | Service | Command |
|---|---|---|
| `client-unit-contract` | none | `uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term --cov-report=xml:.workflow/quality-program/coverage/client-unit-contract.xml -q` |
| `client-hugegraph-integration` | `hugegraph/hugegraph:1.7.0` | `uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short` |

LLM workflow:

| Job | Service | Command |
|---|---|---|
| `llm-unit-contract` | none | `uv run pytest hugegraph-llm/src/tests -m "unit or contract" --cov=hugegraph_llm --cov-report=term --cov-report=xml:.workflow/quality-program/coverage/llm-unit-contract.xml -q` |
| `llm-hugegraph-boundary` | `hugegraph/hugegraph:1.7.0` | `uv run pytest hugegraph-llm/src/tests -m "integration and hugegraph" -v --tb=short` |
| `llm-core-smoke` | `hugegraph/hugegraph:1.7.0` | `uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -v --tb=short` |

External-provider tests are excluded from default PR gates. Unit/contract jobs do not start Docker.

## Coverage Baseline

The plan's original combined baseline command failed because both workspace packages expose `tests.conftest`, causing pytest import-path mismatch during cross-package collection.

Passing command:

```bash
uv run pytest --import-mode=importlib hugegraph-python-client/src/tests hugegraph-llm/src/tests -m 'unit or contract' --cov=pyhugegraph --cov=hugegraph_llm --cov-report=term --cov-report=json:.workflow/quality-program/coverage/combined-baseline.json
```

Result:

```text
185 passed, 2 skipped, 193 deselected, 4 warnings in 12.30s
TOTAL 7975 statements, 3115 covered, 4860 missing, 39% coverage
```

## Ratchet Documentation

Created `docs/quality/coverage-ratchet.md` with:

- initial local ratchet areas
- layer-specific local commands
- combined baseline command with `--import-mode=importlib`
- rules for production bug fixes, HugeGraph boundaries, and external-provider behavior

## Verification

G6 verification commands:

```bash
uv run python -c "import yaml, pathlib; [yaml.safe_load(pathlib.Path(p).read_text()) for p in ['.github/workflows/hugegraph-llm.yml','.github/workflows/hugegraph-python-client.yml']]"
uv run ruff format --check .
uv run ruff check .
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
uv run pytest hugegraph-llm/src/tests -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests -m "integration and hugegraph" -v --tb=short
uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -v --tb=short
```

Results:

- YAML workflow parse: passed
- `git diff --check`: passed
- `uv run ruff format --check .`: 342 files already formatted
- `uv run ruff check .`: all checks passed
- Client unit/contract: 17 passed, 59 deselected
- LLM unit/contract: 168 passed, 2 skipped, 134 deselected
- Client HugeGraph integration: 59 passed, 17 deselected
- LLM HugeGraph integration: 5 passed, 299 deselected
- LLM smoke: 4 passed, 15 deselected
