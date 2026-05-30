# HugeGraph AI Quality Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the HugeGraph AI Quality Program v2 as a restartable, unattended test-quality campaign for `apache/hugegraph-ai`.

**Architecture:** Build quality signal from the bottom up: preflight and ledger first, then strict test taxonomy, deterministic HugeGraph 1.7.0 service fixtures, pyhugegraph contract hardening, `hugegraph-llm` boundary tests, deterministic parser/API/operator coverage, core smoke gates, coverage ratchets, and final reporting. Production code changes are allowed only when a failing or missing test proves a contract gap.

**Tech Stack:** Python 3.10-3.12, uv workspace, pytest, pytest-cov, ruff, GitHub Actions, Docker HugeGraph `hugegraph/hugegraph:1.7.0`, FastAPI TestClient, pyhugegraph, hugegraph-llm.

---

## Source Spec

Implement from:

- `docs/superpowers/specs/2026-05-31-hugegraph-ai-quality-program-design.md`

Do not use the older v1 design if it conflicts with this v2 spec.

## File Structure

Create or modify these files during the plan:

```text
.workflow/quality-program/
  README.md                                  # Campaign purpose, commands, resume instructions
  baseline.md                               # Initial test/coverage/skip state
  quality-state.json                        # Machine-readable campaign state
  checkpoints/
    00-preflight.md
    01-taxonomy.md
    02-service-fixture.md
    03-client-contract.md
    04-llm-boundary.md
    05-parser-api-operator.md
    06-core-smoke.md
    07-coverage-ratchet.md
    08-deferred-refactors.md
  coverage/
    client-baseline.json
    llm-baseline.json
    combined-baseline.json
  reports/
    test-matrix.md
    service-matrix.md
    production-change-ledger.md
    flaky-risk-ledger.md
    deferred-refactors.md
    final-quality-report.md

docs/quality/
  test-taxonomy.md                          # Human-readable test layer contract
  hugegraph-integration.md                  # Docker/service fixture usage
  coverage-ratchet.md                       # Baseline and local ratchet rules

pyproject.toml                              # Strict pytest markers and coverage config
.github/workflows/hugegraph-python-client.yml
.github/workflows/hugegraph-llm.yml

hugegraph-python-client/src/tests/
  conftest.py                               # Shared client fixtures and markers
  client_utils.py                           # Keep or slim legacy helper
  fixtures/hugegraph_service.py             # HugeGraph availability and cleanup helpers
  api/test_*                                # Existing and new client contract tests

hugegraph-llm/src/tests/
  conftest.py                               # Remove global forced skip; add layered fixtures
  fixtures/hugegraph_service.py             # Reuse or wrap client service helpers
  fixtures/fake_llm.py                      # Deterministic fake LLM outputs
  integration/test_*                        # Boundary and smoke tests
  operators/hugegraph_op/test_*             # Boundary unit/contract tests
  operators/llm_op/test_*                   # Parser/operator deterministic tests
  api/test_*                                # API public contract tests
```

Production files may be edited only when a task says so and a test proves the behavior.

## Global Execution Rules

- [ ] Keep changes scoped to the current task.
- [ ] Update `.workflow/quality-program/quality-state.json` after every task.
- [ ] Update the matching checkpoint markdown after every goal.
- [ ] Add an entry to `.workflow/quality-program/reports/production-change-ledger.md` for every production-code edit.
- [ ] Do not silently skip selected HugeGraph integration tests.
- [ ] Do not require real LLM, embedding, reranker, vector DB, or UI credentials outside Layer D.
- [ ] Do not refactor async/streaming, YAML config, demo UI, flow/node/operator architecture, dependency systems, or vector DB abstraction.
- [ ] Commit after each completed goal, not after every tiny step, unless a goal becomes very large.

## P0: Repository Recon and Collision Gate

**Files:**
- Create: `.workflow/quality-program/README.md`
- Create: `.workflow/quality-program/quality-state.json`
- Create: `.workflow/quality-program/checkpoints/00-preflight.md`
- Create: `.workflow/quality-program/reports/test-matrix.md`
- Create: `.workflow/quality-program/reports/service-matrix.md`
- Create: `.workflow/quality-program/reports/flaky-risk-ledger.md`

- [x] **Step P0.1: Read mandatory repository guidance**

Read:

```bash
sed -n '1,220p' AGENTS.md
sed -n '1,260p' hugegraph-llm/AGENTS.md
sed -n '1,260p' rules/README.md
```

Expected: confirm this is a uv workspace; client is a lower-level dependency; `hugegraph-llm` is the main high-risk module; staged workflow requires research-first and explicit checkpoints.

- [x] **Step P0.2: Snapshot branch and open PR collision state**

Run:

```bash
git status --short --branch
gh pr list --repo apache/hugegraph-ai --state open --limit 50 --json number,title,headRefName,baseRefName,updatedAt,mergeable,changedFiles,labels
```

Expected: capture current branch, dirty files, and open PRs. If an open PR touches the same files planned for the current goal, add it to the quarantine section of `00-preflight.md`.

- [x] **Step P0.3: Create initial workflow state**

Create `.workflow/quality-program/quality-state.json` with this exact shape:

```json
{
  "current_goal": "P0",
  "repo_sha_start": "",
  "base_branch": "main",
  "open_pr_snapshot_time": "",
  "goals_completed": [],
  "files_touched": [],
  "production_changes": [],
  "tests_added_or_changed": [],
  "commands_run": [],
  "known_failures": [],
  "deferred_items": [],
  "next_recommended_action": "Complete P0 repository recon and collision gate"
}
```

Fill `repo_sha_start` with `git rev-parse HEAD`. Fill `open_pr_snapshot_time` with `date -u +"%Y-%m-%dT%H:%M:%SZ"`.

- [x] **Step P0.4: Create preflight checkpoint**

Create `.workflow/quality-program/checkpoints/00-preflight.md` with sections:

```markdown
# P0 Preflight Checkpoint

## Repository State

## Open PR Collision Quarantine

## Current CI Workflows

## Current Test Layout

## Current Skip and Service Controls

## Abort Conditions Found

## Next Goal Readiness
```

Populate it using the commands in P0.1 and P0.2 plus:

```bash
rg -n "SKIP_EXTERNAL_SERVICES|SKIP_GREMLIN_TESTS|skip|xfail|pytest.mark|hugegraph:1\\.[0-9]" hugegraph-llm/src/tests hugegraph-python-client/src/tests .github/workflows
```

- [x] **Step P0.5: Create test and service matrix reports**

Create `.workflow/quality-program/reports/test-matrix.md` with this table header:

```markdown
# Test Matrix

| Layer | Module | Current command | Required services | Current issues | Target command |
|---|---|---|---|---|---|
```

Create `.workflow/quality-program/reports/service-matrix.md` with this table header:

```markdown
# Service Matrix

| Service | Default version | Used by | Health check | Required env | Failure behavior |
|---|---|---|---|---|---|
```

At minimum, add HugeGraph:

```markdown
| HugeGraph Server | hugegraph/hugegraph:1.7.0 | Layer B, Layer C graph-boundary smoke | `GET /versions` | `HUGEGRAPH_URL`, `HUGEGRAPH_REQUIRED` | fail if selected and required |
```

- [x] **Step P0.6: Verify no production code changed**

Run:

```bash
git diff --stat
git diff -- . ':!/.workflow/quality-program'
```

Expected: only `.workflow/quality-program/*` changes exist. If production code changed, stop and revert the smallest accidental patch.

- [x] **Step P0.7: Commit P0**

Run:

```bash
git add .workflow/quality-program
git commit -m "docs(quality): add quality program preflight ledger" -m "- initialize restartable campaign state and checkpoints
- document current CI and service matrix scaffolds
- capture PR collision and skip-control audit structure"
```

## G0: Baseline and Test Taxonomy

**Files:**
- Modify: `pyproject.toml`
- Create: `docs/quality/test-taxonomy.md`
- Modify/Create: `hugegraph-python-client/src/tests/conftest.py`
- Modify: `hugegraph-llm/src/tests/conftest.py`
- Create/Update: `.workflow/quality-program/baseline.md`
- Create/Update: `.workflow/quality-program/checkpoints/01-taxonomy.md`
- Create/Update: `.workflow/quality-program/coverage/client-baseline.json`
- Create/Update: `.workflow/quality-program/coverage/llm-baseline.json`

- [x] **Step G0.1: Add strict pytest marker definitions**

Modify root `pyproject.toml` by adding this section if no `[tool.pytest.ini_options]` exists:

```toml
[tool.pytest.ini_options]
markers = [
  "unit: fast deterministic tests without network or Docker",
  "contract: public contract tests; may use mocks but verify stable behavior",
  "integration: tests requiring a real local service such as HugeGraph",
  "hugegraph: tests requiring HugeGraph Server",
  "smoke: end-to-end-ish high-value smoke over production pipeline boundaries",
  "external: tests requiring external provider credentials or non-HugeGraph services",
  "slow: long-running tests excluded from default local loops",
]
addopts = "--strict-markers --strict-config"
```

If `[tool.pytest.ini_options]` exists, merge the marker list without removing existing options.

- [x] **Step G0.2: Create test taxonomy documentation**

Create `docs/quality/test-taxonomy.md`:

```markdown
# HugeGraph AI Test Taxonomy

## Layer A: Unit / Pure Contract

- Markers: `unit` or `contract`.
- No Docker, network, real HugeGraph, real LLM provider, embedding provider, reranker provider, vector DB, or UI service.
- Use fakes, fixtures, monkeypatches, and public APIs.

## Layer B: HugeGraph Server Contract

- Markers: `integration` and `hugegraph`.
- Requires HugeGraph Server, default `hugegraph/hugegraph:1.7.0`.
- If selected with `HUGEGRAPH_REQUIRED=true`, service connection failures fail.
- Must import production code and validate real server behavior.

## Layer C: Core Pipeline Smoke

- Marker: `smoke`; also use `integration` and `hugegraph` when real HugeGraph is required.
- Uses production flow/node/operator code.
- Uses fake LLM and deterministic embeddings/vector fixtures.
- Does not define local replacement pipeline implementations inside tests.

## Layer D: External Provider / Optional E2E

- Markers: `external` and usually `slow`.
- May require real provider credentials or non-HugeGraph services.
- Excluded from default PR gates.

## Required Skip Semantics

Do not silently skip selected Layer B tests. Prefer not selecting integration tests locally.
If `HUGEGRAPH_REQUIRED=true`, unavailable HugeGraph is a failure.
```

- [x] **Step G0.3: Mark current tests in small batches**

Add `pytestmark = pytest.mark.unit` or `pytestmark = pytest.mark.contract` to existing deterministic tests that do not require Docker or network.

Start with:

```text
hugegraph-llm/src/tests/api/test_rag_api.py
hugegraph-llm/src/tests/config/
hugegraph-llm/src/tests/document/
hugegraph-llm/src/tests/middleware/
hugegraph-llm/src/tests/operators/llm_op/
hugegraph-llm/src/tests/models/
hugegraph-python-client/src/tests/api/test_auth_routing.py
hugegraph-python-client/src/tests/api/test_response_validation.py
```

Example file-level marker:

```python
import pytest

pytestmark = pytest.mark.contract
```

For client tests that contact real HugeGraph, mark them:

```python
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]
```

- [x] **Step G0.4: Remove global forced external skip from LLM conftest**

Modify `hugegraph-llm/src/tests/conftest.py` so it does not always set `SKIP_EXTERNAL_SERVICES=true`.

Replace:

```python
os.environ["SKIP_EXTERNAL_SERVICES"] = "true"
```

with:

```python
os.environ.setdefault("SKIP_EXTERNAL_SERVICES", "true")
```

Rationale: Layer A remains safe by default, while integration runs can override the variable.

- [x] **Step G0.5: Run marker collection checks**

Run:

```bash
uv run pytest hugegraph-python-client/src/tests --collect-only -q
uv run pytest hugegraph-llm/src/tests --collect-only -q
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --collect-only -q
uv run pytest hugegraph-llm/src/tests -m "unit or contract" --collect-only -q
```

Expected: no unknown marker errors. If a selected set is empty, mark more existing deterministic tests before continuing.

- [x] **Step G0.6: Generate baseline coverage artifacts**

Run:

```bash
mkdir -p .workflow/quality-program/coverage
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term --cov-report=json:.workflow/quality-program/coverage/client-baseline.json
uv run pytest hugegraph-llm/src/tests -m "unit or contract" --cov=hugegraph_llm --cov-report=term --cov-report=json:.workflow/quality-program/coverage/llm-baseline.json
```

Expected: coverage JSON files exist. If legacy failures appear, record them in `.workflow/quality-program/baseline.md` and continue only if they are unrelated to marker setup.

- [x] **Step G0.7: Write taxonomy checkpoint**

Create `.workflow/quality-program/checkpoints/01-taxonomy.md`:

```markdown
# G0 Taxonomy Checkpoint

## Files Touched

## Markers Added

## Commands Run

## Coverage Baseline

## Failures or Skips Observed

## Next Goal Readiness
```

Update `quality-state.json`:

```json
{
  "current_goal": "G1",
  "next_recommended_action": "Standardize HugeGraph service fixture and CI readiness"
}
```

Preserve existing arrays and append touched files, tests, and commands.

- [x] **Step G0.8: Commit G0**

Run:

```bash
git add pyproject.toml docs/quality/test-taxonomy.md hugegraph-python-client/src/tests hugegraph-llm/src/tests .workflow/quality-program
git commit -m "test(quality): define test taxonomy and baseline" -m "- add strict pytest markers for quality layers
- mark existing deterministic and integration tests
- generate initial client and llm coverage baselines
- document taxonomy, skips, and baseline status"
```

## G1: Test Harness and HugeGraph Service Standardization

**Files:**
- Create: `hugegraph-python-client/src/tests/fixtures/hugegraph_service.py`
- Create: `hugegraph-python-client/src/tests/fixtures/__init__.py`
- Modify/Create: `hugegraph-python-client/src/tests/conftest.py`
- Create: `hugegraph-llm/src/tests/fixtures/hugegraph_service.py`
- Create: `hugegraph-llm/src/tests/fixtures/__init__.py`
- Modify: `hugegraph-llm/src/tests/conftest.py`
- Modify: `.github/workflows/hugegraph-python-client.yml`
- Modify: `.github/workflows/hugegraph-llm.yml`
- Create: `docs/quality/hugegraph-integration.md`
- Create/Update: `.workflow/quality-program/checkpoints/02-service-fixture.md`

- [x] **Step G1.1: Add client HugeGraph service helper**

Create `hugegraph-python-client/src/tests/fixtures/hugegraph_service.py`:

```python
import os
import time
from dataclasses import dataclass

import pytest
import requests


@dataclass(frozen=True)
class HugeGraphService:
    url: str
    graph: str
    user: str
    password: str
    graphspace: str | None


def hugegraph_required() -> bool:
    return os.getenv("HUGEGRAPH_REQUIRED", "false").lower() == "true"


def hugegraph_service_from_env() -> HugeGraphService:
    graphspace = os.getenv("HUGEGRAPH_GRAPHSPACE") or None
    return HugeGraphService(
        url=os.getenv("HUGEGRAPH_URL", "http://127.0.0.1:8080"),
        graph=os.getenv("HUGEGRAPH_GRAPH", "hugegraph"),
        user=os.getenv("HUGEGRAPH_USER", "admin"),
        password=os.getenv("HUGEGRAPH_PASSWORD", "admin"),
        graphspace=graphspace,
    )


def wait_for_hugegraph(service: HugeGraphService, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{service.url}/versions", timeout=5)
            response.raise_for_status()
            return
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"HugeGraph is not ready at {service.url}/versions") from last_error


@pytest.fixture(scope="session")
def hugegraph_service() -> HugeGraphService:
    service = hugegraph_service_from_env()
    if hugegraph_required():
        wait_for_hugegraph(service)
        return service

    try:
        wait_for_hugegraph(service, timeout_seconds=5)
    except RuntimeError as exc:
        pytest.skip(f"HugeGraph integration tests not selected with required service: {exc}")
    return service
```

- [x] **Step G1.2: Wire client conftest to helper**

Create or update `hugegraph-python-client/src/tests/conftest.py`:

```python
from .fixtures.hugegraph_service import hugegraph_service

__all__ = ["hugegraph_service"]
```

- [x] **Step G1.3: Adapt client utility to environment contract**

Modify `hugegraph-python-client/src/tests/client_utils.py` so `ClientUtils` accepts optional service config:

```python
class ClientUtils:
    URL = "http://127.0.0.1:8080"
    GRAPH = "hugegraph"
    USERNAME = "admin"
    PASSWORD = "admin"
    GRAPHSPACE = None
    TIMEOUT = 10

    def __init__(self, service=None):
        if service is not None:
            self.URL = service.url
            self.GRAPH = service.graph
            self.USERNAME = service.user
            self.PASSWORD = service.password
            self.GRAPHSPACE = service.graphspace
        self.client = PyHugeClient(
            url=self.URL,
            user=self.USERNAME,
            pwd=self.PASSWORD,
            graph=self.GRAPH,
            graphspace=self.GRAPHSPACE,
        )
```

Keep the existing initialization methods unchanged.

- [x] **Step G1.4: Add LLM HugeGraph service wrapper**

Create `hugegraph-llm/src/tests/fixtures/hugegraph_service.py`:

```python
import os
import time
from dataclasses import dataclass

import pytest
import requests


@dataclass(frozen=True)
class HugeGraphService:
    url: str
    graph: str
    user: str
    password: str
    graphspace: str | None


def hugegraph_required() -> bool:
    return os.getenv("HUGEGRAPH_REQUIRED", "false").lower() == "true"


def hugegraph_service_from_env() -> HugeGraphService:
    return HugeGraphService(
        url=os.getenv("HUGEGRAPH_URL", "http://127.0.0.1:8080"),
        graph=os.getenv("HUGEGRAPH_GRAPH", "hugegraph"),
        user=os.getenv("HUGEGRAPH_USER", "admin"),
        password=os.getenv("HUGEGRAPH_PASSWORD", "admin"),
        graphspace=os.getenv("HUGEGRAPH_GRAPHSPACE") or None,
    )


def wait_for_hugegraph(service: HugeGraphService, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{service.url}/versions", timeout=5)
            response.raise_for_status()
            return
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"HugeGraph is not ready at {service.url}/versions") from last_error


@pytest.fixture(scope="session")
def hugegraph_service() -> HugeGraphService:
    service = hugegraph_service_from_env()
    if hugegraph_required():
        wait_for_hugegraph(service)
        return service
    try:
        wait_for_hugegraph(service, timeout_seconds=5)
    except RuntimeError as exc:
        pytest.skip(f"HugeGraph integration tests not selected with required service: {exc}")
    return service
```

- [x] **Step G1.5: Update LLM CI to HugeGraph 1.7.0 health checks**

Modify `.github/workflows/hugegraph-llm.yml`:

Replace the manual `docker run ... hugegraph:1.5.0` and `sleep 10` step with a GitHub Actions service:

```yaml
    services:
      hugegraph:
        image: hugegraph/hugegraph:1.7.0
        env:
          PASSWORD: admin
        options: --health-cmd="curl -f http://localhost:8080/versions || exit 1" --health-interval=10s --health-timeout=5s --health-retries=8
        ports:
          - 8080:8080
```

Set integration test env for HugeGraph-selected jobs:

```yaml
      env:
        HUGEGRAPH_REQUIRED: true
        HUGEGRAPH_URL: http://127.0.0.1:8080
        HUGEGRAPH_GRAPH: hugegraph
        HUGEGRAPH_USER: admin
        HUGEGRAPH_PASSWORD: admin
```

- [x] **Step G1.6: Document service usage**

Create `docs/quality/hugegraph-integration.md`:

```markdown
# HugeGraph Integration Test Service

Default image: `hugegraph/hugegraph:1.7.0`

## Environment

```text
HUGEGRAPH_URL=http://127.0.0.1:8080
HUGEGRAPH_GRAPH=hugegraph
HUGEGRAPH_USER=admin
HUGEGRAPH_PASSWORD=admin
HUGEGRAPH_GRAPHSPACE=
HUGEGRAPH_REQUIRED=true|false
```

## Semantics

- If `HUGEGRAPH_REQUIRED=true`, selected integration tests fail when the service is unavailable.
- If `HUGEGRAPH_REQUIRED=false`, local integration tests may skip when no service is present.
- Default unit/contract tests must not require Docker.
```

- [x] **Step G1.7: Run harness verification**

Run:

```bash
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
uv run pytest hugegraph-llm/src/tests -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" --collect-only -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests -m "integration and hugegraph" --collect-only -q
```

Expected: unit/contract tests do not require Docker. Integration collection uses known markers.

- [x] **Step G1.8: Write checkpoint and commit**

Create `.workflow/quality-program/checkpoints/02-service-fixture.md` with files touched, commands run, and failures/skips.

Run:

```bash
git add hugegraph-python-client/src/tests hugegraph-llm/src/tests .github/workflows/hugegraph-llm.yml .github/workflows/hugegraph-python-client.yml docs/quality/hugegraph-integration.md .workflow/quality-program
git commit -m "test(quality): standardize hugegraph integration harness" -m "- add explicit HugeGraph service fixtures and fail/skip semantics
- align LLM CI with HugeGraph 1.7.0 health checks
- document integration environment and service contract"
```

## G2: pyhugegraph Contract Hardening

**Files:**
- Modify: `hugegraph-python-client/src/tests/api/test_schema.py`
- Modify: `hugegraph-python-client/src/tests/api/test_graph.py`
- Modify: `hugegraph-python-client/src/tests/api/test_gremlin.py`
- Modify: `hugegraph-python-client/src/tests/api/test_auth.py`
- Modify: `hugegraph-python-client/src/tests/api/test_auth_routing.py`
- Modify: `hugegraph-python-client/src/tests/api/test_response_validation.py`
- Modify if test proves need: `hugegraph-python-client/src/pyhugegraph/api/*.py`
- Modify if test proves need: `hugegraph-python-client/src/pyhugegraph/utils/*.py`
- Update: `.workflow/quality-program/reports/production-change-ledger.md`
- Create/Update: `.workflow/quality-program/checkpoints/03-client-contract.md`

- [x] **Step G2.1: Convert client integration tests to fixture-driven setup**

In tests that instantiate `ClientUtils()`, use the `hugegraph_service` fixture.

For unittest-style tests, prefer incremental conversion to pytest functions. Example:

```python
import pytest

from ..client_utils import ClientUtils

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


@pytest.fixture()
def client_utils(hugegraph_service):
    utils = ClientUtils(service=hugegraph_service)
    utils.clear_graph_all_data()
    utils.init_property_key()
    utils.init_vertex_label()
    utils.init_edge_label()
    yield utils
    utils.clear_graph_all_data()
```

- [x] **Step G2.2: Add schema CRUD contract tests**

Add tests in `hugegraph-python-client/src/tests/api/test_schema.py` that prove:

```python
def test_schema_create_and_fetch_property_vertex_edge_index(client_utils):
    schema = client_utils.schema
    schema.propertyKey("quality_name").asText().ifNotExist().create()
    schema.propertyKey("quality_score").asInt().ifNotExist().create()
    schema.vertexLabel("quality_person").properties("quality_name", "quality_score").primaryKeys(
        "quality_name"
    ).ifNotExist().create()
    schema.edgeLabel("quality_knows").sourceLabel("quality_person").targetLabel("quality_person").ifNotExist().create()
    schema.indexLabel("quality_person_by_score").onV("quality_person").by("quality_score").range().ifNotExist().create()

    full_schema = schema.getSchema()
    assert "propertykeys" in full_schema
    assert "vertexlabels" in full_schema
    assert "edgelabels" in full_schema
    assert "indexlabels" in full_schema
```

If the existing API returns typed objects instead of dicts, assert the public fields exposed by those objects.

- [x] **Step G2.3: Add graph ID behavior tests**

Add tests in `hugegraph-python-client/src/tests/api/test_graph.py` for:

```python
def test_graph_supports_primary_key_and_custom_string_id(client_utils):
    graph = client_utils.graph
    graph.addVertex("person", {"name": "quality_marko", "age": 29, "city": "Beijing"})
    person = graph.getVertexByCondition(label="person", properties={"name": "quality_marko"}, limit=1)[0]
    assert person.id is not None

    graph.addVertex("book", {"id": "quality-book-1", "name": "Quality Book", "price": 100})
    book = graph.getVertexById("quality-book-1")
    assert book.id == "quality-book-1"
```

If `addVertex` does not accept an `id` property for custom ID labels, write the failing test against the existing public method and fix only the minimal contract gap.

- [x] **Step G2.4: Add Gremlin envelope and error tests**

Extend `hugegraph-python-client/src/tests/api/test_gremlin.py`:

```python
def test_gremlin_error_surface_is_explicit(client_utils):
    with pytest.raises(Exception) as exc_info:
        client_utils.gremlin.exec("g.V2()")
    assert "g.V2" in str(exc_info.value) or "No signature" in str(exc_info.value) or "NotFound" in str(exc_info.value)
```

Keep security-operation tests. Do not add connectivity probes that turn failures into skips.

- [x] **Step G2.5: Add response validation malformed envelope tests**

Extend `hugegraph-python-client/src/tests/api/test_response_validation.py` with malformed and backend-error bodies:

```python
from unittest.mock import Mock

import pytest

from pyhugegraph.utils.util import ResponseValidation


def test_backend_error_envelope_preserves_message():
    response = Mock()
    response.ok = False
    response.status_code = 500
    response.text = '{"exception":"BackendException","message":"quality failure"}'
    response.json.return_value = {"exception": "BackendException", "message": "quality failure"}
    response.request = Mock(body='{"gremlin":"g.V2()"}', url="http://127.0.0.1:8080/gremlin")
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")

    with pytest.raises(Exception) as exc_info:
        ResponseValidation()(response, method="POST", path="/gremlin")

    assert "quality failure" in str(exc_info.value)
```

Add the missing `requests` import if the file does not already have it:

```python
import requests
```

- [x] **Step G2.6: Run client contract suites**

Run:

```bash
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short
```

Expected: Layer A passes; Layer B either passes against running HugeGraph or fails with a classified client/server/setup issue.

- [x] **Step G2.7: Apply minimal production fixes only when tests prove a contract gap**

For each production fix:

1. Keep the failing test.
2. Patch only the smallest relevant file under `hugegraph-python-client/src/pyhugegraph/`.
3. Add a ledger row:

```markdown
| Goal | File | Change | Test proving it | Reason |
|---|---|---|---|---|
| G2 | `path` | `summary` | `pytest path::test_name` | `contract gap` |
```

- [x] **Step G2.8: Write checkpoint and commit**

Create `.workflow/quality-program/checkpoints/03-client-contract.md` and include commands, failures, fixes, and coverage delta.

Run:

```bash
git add hugegraph-python-client/src/tests hugegraph-python-client/src/pyhugegraph .workflow/quality-program
git commit -m "test(client): harden hugegraph contract coverage" -m "- add real HugeGraph contract tests for schema, graph, gremlin, and responses
- use explicit service fixtures for integration setup
- record production fixes with regression evidence"
```

## G3: `hugegraph-llm` HugeGraph Boundary Hardening

**Files:**
- Modify: `hugegraph-llm/src/tests/operators/hugegraph_op/test_schema_manager.py`
- Modify: `hugegraph-llm/src/tests/operators/hugegraph_op/test_commit_to_hugegraph.py`
- Modify: `hugegraph-llm/src/tests/operators/hugegraph_op/test_fetch_graph_data.py`
- Create: `hugegraph-llm/src/tests/integration/test_hugegraph_boundary.py`
- Modify if test proves need: `hugegraph-llm/src/hugegraph_llm/operators/hugegraph_op/*.py`
- Modify if test proves need: `hugegraph-llm/src/hugegraph_llm/nodes/hugegraph_node/*.py`
- Update: `.workflow/quality-program/reports/production-change-ledger.md`
- Create/Update: `.workflow/quality-program/checkpoints/04-llm-boundary.md`

- [x] **Step G3.1: Add real-boundary fixture data**

Create helper functions inside `hugegraph-llm/src/tests/integration/test_hugegraph_boundary.py`:

```python
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.hugegraph]


QUALITY_SCHEMA = {
    "vertices": [
        {"vertex_label": "quality_person", "properties": ["name", "age"], "primary_keys": ["name"]},
        {"vertex_label": "quality_software", "properties": ["name", "lang"], "primary_keys": ["name"]},
    ],
    "edges": [
        {
            "edge_label": "quality_created",
            "source_vertex_label": "quality_person",
            "target_vertex_label": "quality_software",
            "properties": ["date"],
        }
    ],
}

QUALITY_GRAPH = {
    "vertices": [
        {"label": "quality_person", "properties": {"name": "marko", "age": 29}},
        {"label": "quality_software", "properties": {"name": "lop", "lang": "java"}},
    ],
    "edges": [
        {
            "label": "quality_created",
            "source": "marko",
            "target": "lop",
            "properties": {"date": "2026-05-31"},
        }
    ],
}
```

Use this fixture as a source for `Commit2Graph.run({"schema": schema, "vertices": vertices, "edges": edges})`. Convert the compact fixture into the schema format already consumed by `Commit2Graph`: `propertykeys`, `vertexlabels`, and `edgelabels`.

- [x] **Step G3.2: Add schema manager real-service test**

Add a test that imports production `SchemaManager` and asserts real schema readback:

```python
def test_schema_manager_reads_real_schema(hugegraph_service):
    from hugegraph_llm.operators.hugegraph_op.schema_manager import SchemaManager
    from hugegraph_llm.config import hugegraph_config

    hugegraph_config.huge_settings.graph_url = hugegraph_service.url
    hugegraph_config.huge_settings.graph_user = hugegraph_service.user
    hugegraph_config.huge_settings.graph_pwd = hugegraph_service.password
    hugegraph_config.huge_settings.graph_space = hugegraph_service.graphspace

    manager = SchemaManager(graph_name=hugegraph_service.graph)
    context = manager.run({})
    assert "schema" in context
    assert "simple_schema" in context
    assert isinstance(context["schema"]["vertexlabels"], list)
```

- [x] **Step G3.3: Add Commit2Graph write/read integration test**

Add a failing integration test that writes fixture data through production `Commit2Graph`, then reads it using pyhugegraph or production fetch code.

Use this schema/data shape:

```python
QUALITY_COMMIT_SCHEMA = {
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "age", "data_type": "INT", "cardinality": "SINGLE"},
        {"name": "lang", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "date", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
    "vertexlabels": [
        {
            "name": "quality_person",
            "properties": ["name", "age"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        },
        {
            "name": "quality_software",
            "properties": ["name", "lang"],
            "primary_keys": ["name"],
            "nullable_keys": [],
        },
    ],
    "edgelabels": [
        {
            "name": "quality_created",
            "source_label": "quality_person",
            "target_label": "quality_software",
            "properties": ["date"],
        }
    ],
}

QUALITY_COMMIT_DATA = {
    "schema": QUALITY_COMMIT_SCHEMA,
    "vertices": [
        {"label": "quality_person", "properties": {"name": "marko", "age": 29}},
        {"label": "quality_software", "properties": {"name": "lop", "lang": "java"}},
    ],
    "edges": [
        {"label": "quality_created", "outV": "quality_person:marko", "inV": "quality_software:lop", "properties": {"date": "2026-05-31"}}
    ],
}
```

The test must assert:

```text
- expected vertex count is present
- expected edge count is present
- edge source and target are correct
- creation failures raise explicit errors, not secondary NoneType.id errors
```

- [x] **Step G3.4: Add FetchGraphData integration test**

Add a test that imports `FetchGraphData`, reads known graph data, and asserts stable shape:

```python
def test_fetch_graph_data_returns_counts_and_samples(hugegraph_service):
    from pyhugegraph.client import PyHugeClient
    from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData

    client = PyHugeClient(
        url=hugegraph_service.url,
        graph=hugegraph_service.graph,
        user=hugegraph_service.user,
        pwd=hugegraph_service.password,
        graphspace=hugegraph_service.graphspace,
    )
    result = FetchGraphData(client).run({})
    assert {"vertex_num", "edge_num", "vertices", "edges", "note"}.issubset(result)
    assert isinstance(result["vertices"], list)
    assert isinstance(result["edges"], list)
```

- [x] **Step G3.5: Add Gremlin failure-surface test**

Add a test for the production Gremlin execution boundary:

```python
def test_gremlin_execute_surfaces_invalid_query(hugegraph_service):
    from hugegraph_llm.nodes.hugegraph_node.gremlin_execute import GremlinExecuteNode

    node = GremlinExecuteNode()
    node.wk_input = type("Input", (), {"requested_outputs": ["raw_execution_result"]})()
    result = node.operator_schedule({"raw_result": "g.V2()"})
    assert result["template_exec_res"] == ""
    assert "g.V2" in result["raw_exec_res"] or "No signature" in result["raw_exec_res"] or "NotFound" in result["raw_exec_res"]
```

This documents the current node contract: the node surfaces execution errors as result strings instead of raising. If the task changes that production contract, add a regression test and ledger row.

- [x] **Step G3.6: Run LLM boundary suites**

Run:

```bash
uv run pytest hugegraph-llm/src/tests/operators/hugegraph_op -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests/integration/test_hugegraph_boundary.py -v --tb=short
```

Expected: boundary failures classify as service setup, pyhugegraph contract, server contract, or LLM conversion.

- [x] **Step G3.7: Apply minimal LLM boundary fixes**

Allowed fixes include:

```text
- explicit exception before accessing `.id` on failed vertex creation
- stable data transformation for vertex/edge endpoints
- fixture-friendly settings injection
- clearer error messages for fetch/schema/gremlin boundaries
```

For each production edit, add a production ledger row.

- [x] **Step G3.8: Write checkpoint and commit**

Run:

```bash
git add hugegraph-llm/src/tests hugegraph-llm/src/hugegraph_llm .workflow/quality-program
git commit -m "test(llm): harden hugegraph boundary coverage" -m "- add real HugeGraph boundary tests for schema, write, read, and gremlin paths
- classify integration failures by service, client, server, or conversion cause
- apply only regression-backed boundary fixes"
```

## G4: Parser / API / Operator Deterministic Contract Coverage

**Files:**
- Modify: `hugegraph-llm/src/tests/operators/llm_op/test_property_graph_extract.py`
- Modify: `hugegraph-llm/src/tests/operators/llm_op/test_keyword_extract.py`
- Modify: `hugegraph-llm/src/tests/operators/llm_op/test_gremlin_generate.py`
- Modify: `hugegraph-llm/src/tests/api/test_rag_api.py`
- Modify: `hugegraph-llm/src/tests/models/llms/test_openai_client.py`
- Modify: `hugegraph-llm/src/tests/models/llms/test_litellm_client.py`
- Modify: `hugegraph-llm/src/tests/models/embeddings/test_ollama_embedding.py`
- Modify if tests prove need: matching files under `hugegraph-llm/src/hugegraph_llm/`
- Create: `hugegraph-llm/src/tests/fixtures/fake_llm.py`
- Create/Update: `.workflow/quality-program/checkpoints/05-parser-api-operator.md`

- [x] **Step G4.1: Add deterministic fake LLM fixture**

Create `hugegraph-llm/src/tests/fixtures/fake_llm.py`:

```python
class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, prompt=None, messages=None, **kwargs):
        self.calls.append({"prompt": prompt, "messages": messages, "kwargs": kwargs})
        if not self.responses:
            raise AssertionError("FakeLLM has no remaining responses")
        return self.responses.pop(0)

    async def agenerate(self, prompt=None, messages=None, **kwargs):
        return self.generate(prompt=prompt, messages=messages, **kwargs)
```

- [x] **Step G4.2: Add adversarial graph JSON parser tests**

In `test_property_graph_extract.py`, add cases for:

```text
- fenced JSON
- text before/after JSON
- malformed JSON
- missing vertices
- missing edges
- numeric vertex IDs
- duplicate vertices/edges
```

Example:

```python
def test_property_graph_extract_strips_fenced_json():
    from hugegraph_llm.operators.llm_op.property_graph_extract import PropertyGraphExtract
    from tests.fixtures.fake_llm import FakeLLM

    llm = FakeLLM(['```json\n{"vertices": [], "edges": []}\n```'])
    extractor = PropertyGraphExtract(llm=llm)
    result = extractor._extract_and_filter_label({"vertexlabels": [], "edgelabels": []}, llm.generate())
    assert result == []
```

- [x] **Step G4.3: Add keyword parser malformed output tests**

In `test_keyword_extract.py`, add tests for fenced output, empty output, duplicate keywords, and non-list provider text.

Expected assertions:

```text
- output is normalized to the public keyword list contract
- malformed output raises an explicit error or returns documented fallback
- markdown fences do not leak into keywords
```

- [x] **Step G4.4: Add Gremlin-only contract tests**

In `test_gremlin_generate.py`, add tests for:

```text
- fenced gremlin output
- explanation plus gremlin
- empty LLM output
- multiple candidate blocks
```

Assert the public contract expected by callers: Gremlin-only string or explicit failure.

- [x] **Step G4.5: Expand API public-surface tests**

In `hugegraph-llm/src/tests/api/test_rag_api.py`, add FastAPI TestClient tests for:

```text
- graph config field mapping
- LLM config field mapping
- embedding config field mapping
- reranker config field mapping
- invalid request body response shape
- callback exceptions mapped to stable API response
```

Do not test private helper calls when the public route can prove the contract.

- [x] **Step G4.6: Expand provider wrapper error tests**

For OpenAI, LiteLLM, Ollama, embedding, and reranker wrappers:

```text
- authentication error
- empty choices/results
- timeout/connection exception
- malformed SDK response
- retry count behavior where applicable
```

Use mocked SDK calls only. Do not use real credentials.

- [x] **Step G4.7: Run deterministic LLM contract suites**

Run:

```bash
uv run pytest hugegraph-llm/src/tests/operators/llm_op -m "unit or contract" -v --tb=short
uv run pytest hugegraph-llm/src/tests/api -m "unit or contract" -v --tb=short
uv run pytest hugegraph-llm/src/tests/models -m "unit or contract" -v --tb=short
```

Expected: no external calls.

- [x] **Step G4.8: Apply minimal parser/API/operator fixes**

Allowed fixes:

```text
- parsing helpers accept fenced or prefixed output
- malformed output produces explicit failure
- API route uses the correct request field
- provider wrapper preserves useful error context
```

Every fix requires a regression test added in this goal.

- [x] **Step G4.9: Write checkpoint and commit**

Run:

```bash
git add hugegraph-llm/src/tests hugegraph-llm/src/hugegraph_llm .workflow/quality-program
git commit -m "test(llm): expand deterministic contract coverage" -m "- add fake LLM fixtures for parser and operator tests
- cover malformed parser, API, and provider wrapper contracts
- apply regression-backed parser and API fixes"
```

## G5: Core RAG / KG / Text2Gremlin Smoke Gates

**Files:**
- Create: `hugegraph-llm/src/tests/integration/test_core_kg_smoke.py`
- Create: `hugegraph-llm/src/tests/integration/test_core_graphrag_smoke.py`
- Create: `hugegraph-llm/src/tests/integration/test_core_text2gremlin_smoke.py`
- Add fixtures under: `hugegraph-llm/src/tests/data/quality_program/`
- Modify if needed: production code under `hugegraph-llm/src/hugegraph_llm/flows/`, `nodes/`, `operators/`
- Create/Update: `.workflow/quality-program/checkpoints/06-core-smoke.md`

- [x] **Step G5.1: Add smoke fixture data**

Create:

```text
hugegraph-llm/src/tests/data/quality_program/kg_text.txt
hugegraph-llm/src/tests/data/quality_program/kg_graph_output.json
hugegraph-llm/src/tests/data/quality_program/graphrag_documents.json
hugegraph-llm/src/tests/data/quality_program/text2gremlin_schema.json
```

Example `kg_graph_output.json`:

```json
{
  "vertices": [
    {"label": "person", "properties": {"name": "marko", "age": 29}},
    {"label": "software", "properties": {"name": "lop", "lang": "java"}}
  ],
  "edges": [
    {"label": "created", "source": "marko", "target": "lop", "properties": {"date": "2026-05-31"}}
  ]
}
```

- [x] **Step G5.2: Add KG construction smoke**

Create `test_core_kg_smoke.py`:

```python
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.integration, pytest.mark.hugegraph]


def test_kg_construction_smoke_uses_production_code(hugegraph_service):
    from pyhugegraph.client import PyHugeClient
    from hugegraph_llm.operators.hugegraph_op.commit_to_hugegraph import Commit2Graph
    from hugegraph_llm.operators.hugegraph_op.fetch_graph_data import FetchGraphData
    from hugegraph_llm.config import hugegraph_config

    fixture = json.loads(
        Path("hugegraph-llm/src/tests/data/quality_program/kg_graph_output.json").read_text()
    )
    assert fixture["vertices"]
    assert fixture["edges"]

    hugegraph_config.huge_settings.graph_url = hugegraph_service.url
    hugegraph_config.huge_settings.graph_name = hugegraph_service.graph
    hugegraph_config.huge_settings.graph_user = hugegraph_service.user
    hugegraph_config.huge_settings.graph_pwd = hugegraph_service.password
    hugegraph_config.huge_settings.graph_space = hugegraph_service.graphspace

    data = {
        "schema": QUALITY_COMMIT_SCHEMA,
        "vertices": fixture["vertices"],
        "edges": fixture["edges"],
    }
    Commit2Graph().run(data)
    client = PyHugeClient(
        url=hugegraph_service.url,
        graph=hugegraph_service.graph,
        user=hugegraph_service.user,
        pwd=hugegraph_service.password,
        graphspace=hugegraph_service.graphspace,
    )
    summary = FetchGraphData(client).run({})
    assert summary["vertex_num"] >= len(fixture["vertices"])
    assert summary["edge_num"] >= len(fixture["edges"])
```

Import or duplicate `QUALITY_COMMIT_SCHEMA` in this test module. Do not define a local `KGConstructor` replacement.

- [x] **Step G5.3: Add GraphRAG smoke**

Create `test_core_graphrag_smoke.py` that imports production retrieval/flow code and uses deterministic embedding/vector fixtures.

Required assertions:

```text
- production retrieval entrypoint is imported
- fixture documents are indexed or queried through production code
- returned evidence is structured and non-empty
- no real provider credential is read
```

- [x] **Step G5.4: Add Text2Gremlin smoke**

Create `test_core_text2gremlin_smoke.py` that imports production Text2Gremlin/Gremlin generation code and uses fake LLM output.

Required assertions:

```text
- output is Gremlin-only after normalization
- optional execution against HugeGraph returns expected shape
- invalid fake output produces explicit failure
```

- [x] **Step G5.5: Convert weak mock-only integration tests**

Inspect:

```text
hugegraph-llm/src/tests/integration/test_graph_rag_pipeline.py
hugegraph-llm/src/tests/integration/test_kg_construction.py
hugegraph-llm/src/tests/integration/test_rag_pipeline.py
```

For each test:

```text
- If it imports production code and asserts behavior, keep it and mark layer correctly.
- If it defines local replacement pipeline classes, convert it to a unit test or replace it with a production-code smoke.
- If it only asserts mocks were called, add a stronger behavior assertion or document replacement in flaky-risk ledger.
```

- [x] **Step G5.6: Run smoke gates**

Run:

```bash
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -v --tb=short
uv run pytest hugegraph-llm/src/tests/integration -m "smoke and not hugegraph" -v --tb=short
```

Expected: smoke tests are deterministic. HugeGraph-required smoke fails only for classified service/setup/boundary reasons.

- [x] **Step G5.7: Write checkpoint and commit**

Run:

```bash
git add hugegraph-llm/src/tests hugegraph-llm/src/hugegraph_llm .workflow/quality-program
git commit -m "test(llm): add core pipeline smoke gates" -m "- add deterministic KG, GraphRAG, and Text2Gremlin smoke coverage
- ensure smoke tests import production code
- classify or replace weak mock-only integration tests"
```

## G6: Coverage Ratchet and CI Split

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/hugegraph-python-client.yml`
- Modify: `.github/workflows/hugegraph-llm.yml`
- Create: `docs/quality/coverage-ratchet.md`
- Create/Update: `.workflow/quality-program/coverage/combined-baseline.json`
- Create/Update: `.workflow/quality-program/checkpoints/07-coverage-ratchet.md`

- [ ] **Step G6.1: Create coverage ratchet documentation**

Create `docs/quality/coverage-ratchet.md`:

```markdown
# Coverage Ratchet

## Principles

- Start with local areas, not a full-repo threshold.
- New production logic requires tests.
- Bug fixes require regression tests.
- HugeGraph boundaries need Layer B or Layer C evidence.
- Thresholds may start low but must not decrease.

## Initial Ratchet Areas

- `pyhugegraph`
- `hugegraph_llm.operators.hugegraph_op`
- `hugegraph_llm.operators.llm_op`
- `hugegraph_llm.api`
- `hugegraph_llm.api.models`
```

- [ ] **Step G6.2: Generate combined coverage baseline**

Run:

```bash
uv run pytest hugegraph-python-client/src/tests hugegraph-llm/src/tests \
  -m "unit or contract" \
  --cov=pyhugegraph \
  --cov=hugegraph_llm \
  --cov-report=term \
  --cov-report=json:.workflow/quality-program/coverage/combined-baseline.json
```

Expected: combined baseline file exists. Do not enforce a high threshold yet.

- [ ] **Step G6.3: Split client CI into layer jobs**

Modify `.github/workflows/hugegraph-python-client.yml` into at least:

```text
client-unit-contract
client-hugegraph-integration
```

Required properties:

```text
- unit/contract job does not start or require Docker
- integration job uses HugeGraph 1.7.0 service
- integration job sets HUGEGRAPH_REQUIRED=true
- coverage artifact is uploaded when feasible
```

- [ ] **Step G6.4: Split LLM CI into layer jobs**

Modify `.github/workflows/hugegraph-llm.yml` into at least:

```text
llm-unit-contract
llm-hugegraph-boundary
llm-core-smoke
```

Required properties:

```text
- unit/contract job excludes integration, hugegraph, external, slow
- hugegraph-boundary job starts HugeGraph 1.7.0 and sets HUGEGRAPH_REQUIRED=true
- core-smoke job runs smoke tests with deterministic fakes
- external tests are not default PR gates
```

- [ ] **Step G6.5: Add local ratchet commands**

Document commands in `docs/quality/coverage-ratchet.md`:

```bash
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term
uv run pytest hugegraph-llm/src/tests/operators/hugegraph_op -m "unit or contract" --cov=hugegraph_llm.operators.hugegraph_op --cov-report=term
uv run pytest hugegraph-llm/src/tests/operators/llm_op -m "unit or contract" --cov=hugegraph_llm.operators.llm_op --cov-report=term
uv run pytest hugegraph-llm/src/tests/api -m "unit or contract" --cov=hugegraph_llm.api --cov-report=term
```

- [ ] **Step G6.6: Run full local verification**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
uv run pytest hugegraph-llm/src/tests -m "unit or contract" -q
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -v --tb=short
HUGEGRAPH_REQUIRED=true uv run pytest hugegraph-llm/src/tests -m "integration and hugegraph" -v --tb=short
uv run pytest hugegraph-llm/src/tests/integration -m "smoke" -v --tb=short
```

Expected: failures are either fixed or recorded with classification and next action.

- [ ] **Step G6.7: Write checkpoint and commit**

Run:

```bash
git add pyproject.toml .github/workflows docs/quality/coverage-ratchet.md .workflow/quality-program
git commit -m "ci(quality): split test gates and add coverage ratchet" -m "- separate unit, contract, integration, and smoke CI paths
- publish baseline coverage artifacts and ratchet commands
- keep external provider tests outside default PR gates"
```

## G7: Deferred Refactor Queue and Final Report

**Files:**
- Create/Update: `.workflow/quality-program/reports/deferred-refactors.md`
- Create/Update: `.workflow/quality-program/reports/production-change-ledger.md`
- Create/Update: `.workflow/quality-program/reports/flaky-risk-ledger.md`
- Create/Update: `.workflow/quality-program/reports/final-quality-report.md`
- Create/Update: `.workflow/quality-program/checkpoints/08-deferred-refactors.md`

- [ ] **Step G7.1: Create deferred refactor report**

Create `.workflow/quality-program/reports/deferred-refactors.md` with one section per item:

```markdown
# Deferred Refactors

## Async/Streaming API Full-Chain Refactor

- blocked_by: `#179` or successor PR status
- affected modules: `hugegraph-llm/src/hugegraph_llm/api/`, flows, nodes
- why deferred: broad async contract collision
- prerequisite tests: parser/API contract tests, core smoke tests
- trigger condition: upstream async/streaming PR merged or closed
- suggested future goal: async/streaming boundary and smoke gate
```

Add matching sections for YAML config, demo UI decomposition, flow/node/operator boundary redesign, vector DB backend abstraction cleanup, broader dependency/config cleanup, and optional MCP/tool-surface integration.

- [ ] **Step G7.2: Finalize production change ledger**

Ensure `.workflow/quality-program/reports/production-change-ledger.md` contains:

```markdown
# Production Change Ledger

| Goal | File | Change | Test proving it | Reason | Risk |
|---|---|---|---|---|---|
```

Every production file edit from G2-G6 must have a row.

- [ ] **Step G7.3: Finalize flaky risk ledger**

Ensure `.workflow/quality-program/reports/flaky-risk-ledger.md` contains:

```markdown
# Flaky Risk Ledger

| Test or area | Risk | Current mitigation | Future action |
|---|---|---|---|
```

Include Docker readiness, HugeGraph cleanup, external provider exclusion, and smoke fixture determinism.

- [ ] **Step G7.4: Write final quality report**

Create `.workflow/quality-program/reports/final-quality-report.md` with:

```markdown
# Final Quality Report

## Summary

## Test Matrix

## Coverage Baseline and Ratchets

## Commands Run

## Production Changes

## Failures, Skips, and Known Risks

## Deferred Refactors

## Maintainer Review Notes

## Recommended Next Actions
```

Include exact commands and final status for each layer.

- [ ] **Step G7.5: Run final sanity checks**

Run:

```bash
rg -n "TBD|PLACEHOLDER|fill in|implement later" .workflow/quality-program docs/quality
git status --short
uv run ruff format --check .
uv run ruff check .
```

Expected: no placeholder text. Ruff checks pass or failures are recorded with exact reason.

- [ ] **Step G7.6: Commit final reports**

Run:

```bash
git add .workflow/quality-program docs/quality
git commit -m "docs(quality): finalize quality program report" -m "- document deferred refactors and production change evidence
- summarize test matrix, coverage ratchets, and remaining risks
- provide maintainer-ready final quality report"
```

## Plan Self-Review Checklist

- [ ] Spec coverage: P0 maps to preflight/collision gate and state ledger.
- [ ] Spec coverage: G0 maps to strict marker definitions and coverage baseline.
- [ ] Spec coverage: G1 maps to deterministic HugeGraph 1.7.0 service fixtures and CI readiness.
- [ ] Spec coverage: G2 maps to pyhugegraph contract hardening.
- [ ] Spec coverage: G3 maps to `hugegraph-llm` HugeGraph boundary hardening.
- [ ] Spec coverage: G4 maps to parser/API/operator deterministic contract coverage.
- [ ] Spec coverage: G5 maps to production-code core smoke gates and anti mock-only integration rules.
- [ ] Spec coverage: G6 maps to coverage ratchet and CI split.
- [ ] Spec coverage: G7 maps to deferred refactor queue and final report.
- [ ] No task requires real LLM, embedding, reranker, vector DB, or UI credentials in default gates.
- [ ] No task performs async/streaming, YAML config, demo UI, flow/node/operator architecture, dependency-system, or vector DB abstraction refactors.
- [ ] Every production-code change task requires a proving test and ledger entry.
- [ ] Every goal ends with a checkpoint and commit.
