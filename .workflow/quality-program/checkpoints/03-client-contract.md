# G2 Client Contract Checkpoint

## Status

Partially complete; service-bound client contract tests remain blocked.

## Blocker

Required HugeGraph service is unavailable locally:

- `docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'` failed because the Docker daemon is not reachable at `/Users/imbajin/.orbstack/run/docker.sock`.
- Direct `GET http://127.0.0.1:8080/versions` failed with `ConnectionRefusedError`.

The plan requires Layer B client contract tests to run against a real HugeGraph service and forbids silently skipping selected HugeGraph integration tests. Service-bound schema, graph ID, and Gremlin contract additions remain paused until HugeGraph `1.7.0` is reachable.

## Completed Non-Service Slice

- Added malformed/backend error envelope contract tests for `ResponseValidation`.
- Proved the 500 backend envelope regression red first:
  - `test_backend_error_envelope_preserves_message` failed because the raised exception was plain `500 Server Error`.
- Applied the minimal production fix:
  - Prefer backend `message` over `exception` when extracting error details.
  - Raise `Server Exception: {details}` for non-404 HTTP status codes instead of re-raising raw `HTTPError`.
- Tightened legacy client integration setup:
  - `ClientUtils()` now honors `HUGEGRAPH_*` env vars when no explicit service object is passed.
  - A class-scope autouse fixture gates `hugegraph`-marked tests through `hugegraph_service` before unittest `setUpClass()`.

## Commands Run

```bash
docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'
uv run python -c "import requests; print(requests.get('http://127.0.0.1:8080/versions', timeout=5).text[:200])"
uv run pytest hugegraph-python-client/src/tests/api/test_response_validation.py -q
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short --maxfail=1
uv run ruff format --check hugegraph-python-client/src/tests/conftest.py hugegraph-python-client/src/tests/client_utils.py hugegraph-python-client/src/tests/api/test_response_validation.py hugegraph-python-client/src/pyhugegraph/utils/util.py
uv run ruff check hugegraph-python-client/src/tests/conftest.py hugegraph-python-client/src/tests/client_utils.py hugegraph-python-client/src/tests/api/test_response_validation.py hugegraph-python-client/src/pyhugegraph/utils/util.py
uv run pre-commit run trailing-whitespace --files hugegraph-python-client/src/pyhugegraph/utils/util.py
git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check
```

## Files Touched

- `.workflow/quality-program/checkpoints/03-client-contract.md`
- `.workflow/quality-program/quality-state.json`
- `.workflow/quality-program/reports/flaky-risk-ledger.md`
- `.workflow/quality-program/reports/production-change-ledger.md`
- `hugegraph-python-client/src/tests/conftest.py`
- `hugegraph-python-client/src/tests/client_utils.py`
- `hugegraph-python-client/src/tests/api/test_response_validation.py`
- `hugegraph-python-client/src/pyhugegraph/utils/util.py`

## Production Changes

- `hugegraph-python-client/src/pyhugegraph/utils/util.py`
  - Preserves parsed backend error details for 500-class error envelopes.
  - Proving test: `uv run pytest hugegraph-python-client/src/tests/api/test_response_validation.py -q`

## Tests Added or Changed

- Added `test_backend_error_envelope_preserves_message`.
- Added `test_malformed_error_body_uses_response_text`.
- Added client conftest service gate for `hugegraph`-marked tests.
- Updated `ClientUtils()` to read `HUGEGRAPH_*` env vars for legacy unittest-style integrations.

## Failure Classification

- Service setup failure: HugeGraph Server `1.7.0` is not reachable, and Docker cannot start or inspect containers because the local daemon is unavailable.
- `HUGEGRAPH_REQUIRED=true` integration command now fails at the shared `/versions` readiness fixture before test class setup, not during unrelated cleanup.
- `util.py` keeps its existing CRLF line-ending style; whitespace verification used `cr-at-eol` to avoid a whole-file line-ending rewrite.

## Resume Condition

Start a HugeGraph `1.7.0` service reachable at `http://127.0.0.1:8080`, or start the local Docker/OrbStack daemon so the service can be launched with:

```bash
docker run -d --name hugegraph-quality -p 8080:8080 -e PASSWORD=admin hugegraph/hugegraph:1.7.0
```

Then resume G2 from Step G2.2.
