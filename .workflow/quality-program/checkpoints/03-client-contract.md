# G2 Client Contract Checkpoint

## Status

Complete.

## Service Resolution

Layer B was resumed after starting local Docker/OrbStack and HugeGraph Server `1.7.0`:

- Image: `hugegraph/hugegraph:1.7.0`
- Container: `hugegraph-quality`
- Health check: `GET http://127.0.0.1:8080/versions`
- Observed version: `{"core":"1.7.0","gremlin":"3.5.1","api":"0.71.0.0"}`

The earlier G2 service setup blocker is resolved for this checkpoint. It remains recorded in the flaky-risk ledger as a local environment dependency.

## Completed Scope

- Added real HugeGraph schema contract coverage for property key, vertex label, edge label, index label, full schema fetch, and typed fetch APIs.
- Added real graph ID behavior coverage for primary-key vertex lookup and custom string ID vertex lookup.
- Added real Gremlin error-surface coverage for invalid traversal execution through production Gremlin client code.
- Added malformed/backend error envelope contract tests for `ResponseValidation`.
- Tightened legacy client integration setup so `hugegraph`-marked unittest classes are gated by the shared service fixture before `setUpClass()`.
- Preserved `ClientUtils()` env-driven compatibility for legacy test callers while allowing fixture-injected HugeGraph service config.

## Commands Run

```bash
docker pull hugegraph/hugegraph:1.7.0
docker run -d --name hugegraph-quality -p 8080:8080 -e PASSWORD=admin hugegraph/hugegraph:1.7.0
uv run python -c 'import requests; r=requests.get("http://127.0.0.1:8080/versions", timeout=5); print(r.status_code); print(r.text)'
uv run pytest hugegraph-python-client/src/tests/api/test_response_validation.py -q
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short
uv run ruff format --check hugegraph-python-client/src/tests/conftest.py hugegraph-python-client/src/tests/api/test_schema.py hugegraph-python-client/src/tests/api/test_graph.py hugegraph-python-client/src/tests/api/test_gremlin.py
uv run ruff check hugegraph-python-client/src/tests/conftest.py hugegraph-python-client/src/tests/api/test_schema.py hugegraph-python-client/src/tests/api/test_graph.py hugegraph-python-client/src/tests/api/test_gremlin.py
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term --cov-report=json:.workflow/quality-program/coverage/client-g2.json
```

## Verification Result

| Layer | Command | Result |
|---|---|---|
| Client unit/contract | `uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q` | `17 passed, 59 deselected` |
| Client HugeGraph integration | `HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short` | `59 passed, 17 deselected` |
| Targeted G2 service contracts | `HUGEGRAPH_REQUIRED=true uv run pytest ...test_schema... ...test_graph... ...test_gremlin... -q` | `3 passed` |
| Formatting | `uv run ruff format --check ...` | `4 files already formatted` |
| Lint | `uv run ruff check ...` | `All checks passed` |

## Coverage Delta

| Artifact | Coverage |
|---|---:|
| `.workflow/quality-program/coverage/client-baseline.json` | `45.0665%` |
| `.workflow/quality-program/coverage/client-g2.json` | `45.1774%` |

The small coverage increase is expected; G2 primarily improves service-boundary confidence by adding real HugeGraph contract assertions rather than broad line coverage.

## Files Touched

- `.workflow/quality-program/checkpoints/03-client-contract.md`
- `.workflow/quality-program/coverage/client-g2.json`
- `.workflow/quality-program/quality-state.json`
- `.workflow/quality-program/reports/flaky-risk-ledger.md`
- `.workflow/quality-program/reports/production-change-ledger.md`
- `docs/plans/2026-05-31-hugegraph-ai-quality-program.md`
- `hugegraph-python-client/src/tests/conftest.py`
- `hugegraph-python-client/src/tests/client_utils.py`
- `hugegraph-python-client/src/tests/api/test_response_validation.py`
- `hugegraph-python-client/src/tests/api/test_schema.py`
- `hugegraph-python-client/src/tests/api/test_graph.py`
- `hugegraph-python-client/src/tests/api/test_gremlin.py`
- `hugegraph-python-client/src/pyhugegraph/utils/util.py`

## Production Changes

| File | Change | Proving test |
|---|---|---|
| `hugegraph-python-client/src/pyhugegraph/utils/util.py` | Preserve parsed backend error details for non-404 HTTP errors and prefer server `message` over `exception`. | `uv run pytest hugegraph-python-client/src/tests/api/test_response_validation.py -q` |

No additional production-code changes were needed for schema CRUD, graph ID behavior, or Gremlin error-surface coverage.

## Failure Classification

- Historical service setup failure: before Docker/OrbStack was started, `HUGEGRAPH_REQUIRED=true` failed at the shared `/versions` readiness fixture and no selected HugeGraph tests were silently skipped.
- Current G2 status: no client contract, server contract, or service setup failures remain in the verified G2 commands.
- `util.py` keeps its existing CRLF line-ending style from the repository; earlier whitespace verification used `cr-at-eol` to avoid a whole-file line-ending rewrite.

## Next Goal Readiness

G3 can begin. The local HugeGraph `1.7.0` service is available at `http://127.0.0.1:8080` for LLM HugeGraph boundary tests.
