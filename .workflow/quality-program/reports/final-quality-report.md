# Final Quality Report

## Summary

The HugeGraph AI Quality Program v2 completed P0-G7 on branch `goal-test`.

The program changed the quality gates from broad, mixed test execution into explicit layers:

```text
Layer A  unit/contract  no Docker, no live providers
Layer B  HugeGraph      HugeGraph 1.7.0, fail when selected service is unavailable
Layer C  core smoke     deterministic fake LLMs plus production operators/flows
Layer D  external       opt-in only, not default PR gates
```

## Test Matrix

| Layer | Module | Command | Final result |
|---|---|---|---|
| Layer A | `hugegraph-python-client` | `uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q` | 17 passed, 59 deselected |
| Layer A | `hugegraph-llm` | `uv run pytest hugegraph-llm/src/tests -m "unit or contract" -q` | 168 passed, 2 skipped, 134 deselected |
| Layer B | `hugegraph-python-client` | `HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short` | 59 passed, 17 deselected |
| Layer B | `hugegraph-llm` | `HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests -m "integration and hugegraph" -v --tb=short` | 5 passed, 299 deselected |
| Layer C | `hugegraph-llm` | `uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -v --tb=short` | 4 passed, 15 deselected |
| Formatting | workspace | `uv run ruff format --check .` | 342 files already formatted |
| Lint | workspace | `uv run ruff check .` | all checks passed |

## Coverage Baseline and Ratchets

Baseline artifacts:

| Artifact | Scope | Coverage |
|---|---|---:|
| `.workflow/quality-program/coverage/client-baseline.json` | initial `pyhugegraph` Layer A | 45% |
| `.workflow/quality-program/coverage/llm-baseline.json` | initial `hugegraph_llm` Layer A | 34% |
| `.workflow/quality-program/coverage/combined-baseline.json` | final combined unit/contract baseline | 39% |

The combined baseline required `--import-mode=importlib` because both workspace packages expose `tests.conftest` during cross-package collection.

Initial ratchet areas are documented in `docs/quality/coverage-ratchet.md`:

- `pyhugegraph`
- `hugegraph_llm.operators.hugegraph_op`
- `hugegraph_llm.operators.llm_op`
- `hugegraph_llm.api`
- `hugegraph_llm.api.models`

## Commands Run

Final G6 verification:

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

Final G7 sanity checks:

- placeholder scan over `.workflow/quality-program` and `docs/quality`: no unresolved placeholder content after removing self-matches from this report
- `git status --short`: only G7 report, state, and plan files pending before commit
- `uv run ruff format --check .`: 342 files already formatted
- `uv run ruff check .`: all checks passed

## Production Changes

| Goal | File | Change | Proving test |
|---|---|---|---|
| G2 | `hugegraph-python-client/src/pyhugegraph/utils/util.py` | Preserve backend error envelope details for non-404 HTTP errors and prefer server `message` over `exception`. | `uv run pytest hugegraph-python-client/src/tests/api/test_response_validation.py -q` |
| G3 | `hugegraph-llm/src/hugegraph_llm/operators/hugegraph_op/commit_to_hugegraph.py` | Map primary-key `label:value` edge endpoints to server-created VIDs and raise explicit vertex creation errors. | `uv run pytest hugegraph-llm/src/tests/operators/hugegraph_op/test_commit_to_hugegraph.py::TestCommit2Graph::test_load_into_graph_raises_explicit_error_when_vertex_creation_fails -q`; `HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests/integration/test_hugegraph_boundary.py -v --tb=short` |
| G4 | `hugegraph-llm/src/hugegraph_llm/api/rag_api.py` | Map `/config/llm` to `llm_settings.chat_llm_type`. | `uv run pytest hugegraph-llm/src/tests/api -m "unit or contract" -v --tb=short` |

No production code changed in G5-G7.

## Failures, Skips, and Known Risks

- The original combined coverage command failed with pytest import-path mismatch because both packages define `tests.conftest`; rerun with `--import-mode=importlib` passed.
- Two LLM model tests remain skipped inside the Layer A selection; they are explicit pytest skips, not service-bound silent skips.
- Layer B commands used local HugeGraph `hugegraph/hugegraph:1.7.0` and `HUGEGRAPH_REQUIRED=true`.
- GraphRAG smoke emits known NLTK BLEU zero-overlap warnings for short deterministic strings; assertions do not depend on BLEU score value.
- Legacy mock-only integration tests remain documented as future cleanup. New authoritative smoke tests import production code.

## Deferred Refactors

Deferred items are documented in `.workflow/quality-program/reports/deferred-refactors.md`:

- async/streaming API full-chain refactor
- YAML config migration
- demo UI decomposition
- flow/node/operator boundary redesign
- vector DB backend abstraction cleanup
- broader dependency/config cleanup
- optional MCP/tool-surface integration

## Maintainer Review Notes

- CI now separates default PR gates by layer and keeps external-provider tests out of default execution.
- HugeGraph integration jobs use `hugegraph/hugegraph:1.7.0` and selected integration tests fail when the required service is unavailable.
- Smoke tests are deterministic and exercise production code at KG, GraphRAG, and Text2Gremlin boundaries.
- Coverage ratchets start from local areas instead of imposing a full-repository threshold.

## Recommended Next Actions

1. Review CI runtime after the workflow split and adjust matrix breadth if runtime is too high.
2. Decide whether legacy mock-only integration tests should be converted, demoted, or removed.
3. Add targeted ratchet thresholds for the initial areas once maintainers agree on acceptable floors.
4. Re-check open PR collisions before starting any deferred refactor.
