# HugeGraph AI Quality Program Design v2

Date: 2026-05-31
Target repo: `apache/hugegraph-ai`
Primary execution mode: Codex `/goal`, long-running, unattended, restartable, high-signal test refactor.
Implementation plan: `docs/plans/2026-05-31-hugegraph-ai-quality-program.md`

## Executive Summary

This v2 keeps the original direction: test signal first, lower-level HugeGraph client boundary first, then `hugegraph-llm` boundary, deterministic LLM logic tests, core smoke gates, and only then coverage ratchets and guarded cleanup.

The main upgrade is that the program is now designed as a controlled autonomous quality campaign, not only as a list of test targets. It adds:

- a preflight/collision gate before any edits,
- strict test-layer semantics,
- explicit “no mock-only integration” rules,
- deterministic HugeGraph 1.7.0 service fixtures,
- machine-readable checkpoints,
- skip/fail semantics that cannot hide broken services,
- coverage baselines and ratchets that are reproducible,
- per-goal abort/rollback rules,
- PR-collision quarantine,
- an evidence ledger for production changes,
- a final quality report that lets maintainers review the work without reading the whole diff.

## Current Design Score

Overall score for the original v1: **82 / 100**.

| Area | Score | Assessment |
|---|---:|---|
| Strategic direction | 9/10 | Correctly starts with test signal and pyhugegraph boundary before LLM layers. |
| Scope control | 8.5/10 | Good deferred-refactor list; needs stronger file quarantine and diff budget. |
| Test taxonomy | 7.5/10 | Good concept; needs strict marker definitions and enforcement. |
| Real-service confidence | 8/10 | Correct priority, but needs deterministic service lifecycle and graph isolation. |
| LLM deterministic tests | 8/10 | Good default; needs stronger fake-contract fixtures and anti-mock rules. |
| CI/coverage design | 7/10 | Good phased ratchet; needs concrete baseline artifacts and split jobs. |
| Unattended execution safety | 6.5/10 | Main weakness: lacks resumable state, abort rules, conflict quarantine, and quality ledger. |
| Maintainability/reviewability | 7.5/10 | Good checkpoints; needs standardized report schema and PR-sized slices. |

## Non-negotiable Invariants

1. Do not add behavior-free coverage tests.
2. Do not silently skip required service failures.
3. Do not change production code without a regression, contract, or integration test.
4. Do not rewrite async/streaming, YAML config, demo UI, flow/node/operator architecture, dependency systems, or vector DB abstraction as part of this campaign.
5. Do not introduce real LLM, embedding, reranker, or vector DB credentials into default tests.
6. Do not create integration tests that define local fake pipeline implementations instead of importing real production code.
7. Do not merge unrelated formatting-only rewrites into behavior/test changes.
8. Do not broaden into `hugegraph-ml` or `vermeer-python-client` unless a root workspace or CI change directly requires validation.

## Test Layer Contract

### Layer A: Unit / Pure Contract

- No Docker.
- No network.
- No real HugeGraph.
- No real LLM, embedding, reranker, vector DB, or UI service.
- Uses fake LLMs, fixtures, monkeypatches, and public APIs.
- Marker: `unit` or `contract`, never `integration`.

Examples:

- parser robustness,
- request/response model behavior,
- API route behavior via FastAPI TestClient,
- provider wrapper error mapping with mocked SDK clients,
- operator contracts that do not cross service boundaries.

### Layer B: HugeGraph Server Contract

- Requires Docker HugeGraph, default image `hugegraph/hugegraph:1.7.0`.
- Proves real HTTP/Gremlin/schema/graph behavior.
- Does not call real LLM providers.
- Marker: `integration` plus `hugegraph`.
- If selected in CI or with `HUGEGRAPH_REQUIRED=true`, connection failures fail.

Examples:

- pyhugegraph schema CRUD,
- pyhugegraph vertex/edge CRUD,
- Gremlin result and error envelopes,
- auth/graphspace route behavior,
- `hugegraph-llm` schema/read/write/gremlin boundary against real HugeGraph.

### Layer C: Core Pipeline Smoke

- Uses production flow/node/operator code.
- Uses fake LLM and deterministic embedding/vector fixtures.
- May use real HugeGraph for graph boundary proof.
- Marker: `smoke`, optionally also `integration` and `hugegraph`.
- Must not define a local replacement pipeline class inside the test.

Examples:

- KG construction smoke: fake graph JSON output -> normalization -> commit -> readback.
- GraphRAG smoke: fixture graph/doc -> deterministic retrieval -> structured evidence.
- Text2Gremlin smoke: fixture schema -> fake Gremlin output -> contract normalization -> optional execution.

### Layer D: External Provider / Optional E2E

- Real LLM/embedding/reranker/vector DB/UI calls.
- Marker: `external` and usually `slow`.
- Not a default PR gate.
- CI only with explicit scheduled/manual workflow and secrets present.

## Required pytest Marker Definitions

Add or consolidate in the nearest appropriate `pyproject.toml` / pytest config:

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

## Service Fixture Standard

Create one shared HugeGraph test service fixture per module or workspace:

- CI starts `hugegraph/hugegraph:1.7.0`.
- Local tests can use an already running service or a helper script.
- Health readiness checks `/versions` with retries.
- No blind `sleep 10` readiness.
- Tests use a unique graph/graphspace/test namespace where supported, or perform strict cleanup before and after.
- Integration fixtures must fail if `HUGEGRAPH_REQUIRED=true` and service is unavailable.
- Local opt-out should be achieved by not selecting integration tests, not by converting selected tests into silent skips.

Suggested environment contract:

```text
HUGEGRAPH_URL=http://127.0.0.1:8080
HUGEGRAPH_GRAPH=hugegraph
HUGEGRAPH_USER=admin
HUGEGRAPH_PASSWORD=admin
HUGEGRAPH_GRAPHSPACE=
HUGEGRAPH_REQUIRED=true|false
HUGEGRAPH_VERSION_EXPECTED=1.7.0
```

## Automation State and Checkpoint Ledger

All long-running work must maintain a resumable ledger:

```text
.workflow/quality-program/
  README.md
  baseline.md
  quality-state.json
  checkpoints/
    00-preflight.md
    01-taxonomy.md
    02-client-contract.md
    03-llm-boundary.md
    04-parser-api-operator.md
    05-core-smoke.md
    06-coverage-ratchet.md
    07-deferred-refactors.md
  coverage/
    client-baseline.json
    llm-baseline.json
    combined-baseline.json
  reports/
    test-matrix.md
    service-matrix.md
    production-change-ledger.md
    flaky-risk-ledger.md
    final-quality-report.md
```

`quality-state.json` minimum schema:

```json
{
  "current_goal": "G0",
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
  "next_recommended_action": ""
}
```

After each goal, update both the markdown checkpoint and `quality-state.json`.

## Abort, Pause, and Rollback Rules

Abort or pause the current goal if any of these occur:

1. Open PR collision in the same core files is discovered after edits start.
2. Required Docker service cannot start after the standard retry budget in CI-like mode.
3. A test requires real provider credentials outside Layer D.
4. Production changes exceed the allowed fix categories.
5. A change requires async/streaming, YAML config migration, demo UI decomposition, or full pipeline architecture redesign.
6. Coverage improvement is only achievable by weak assertions or tests that mock away the behavior under test.
7. A failing integration test cannot be classified as service setup, client contract, server contract, or LLM conversion issue.

Rollback strategy:

- Revert only the smallest risky patch, not the whole campaign.
- Keep tests that expose a real bug when possible, marking the production fix as deferred only if it collides with a blocked refactor.
- Record the rollback in the checkpoint ledger.

## Preflight Goal: P0 Repository Recon and Collision Gate

Before editing:

1. Read root `AGENTS.md` and module `AGENTS.md` files.
2. Read `rules/README.md` and follow repository staged-workflow expectations.
3. Snapshot open PRs:

```bash
gh pr list --repo apache/hugegraph-ai --state open --limit 50 --json number,title,headRefName,baseRefName,updatedAt,mergeable,changedFiles,labels
```

4. Inspect current CI workflows and test commands.
5. Inspect current marker definitions, conftest files, skip environment variables, and Docker image versions.
6. Generate a file-collision watchlist:

```text
PR collision quarantine
- config: #350 / #277 and successors
- async/streaming API: #179 and successors
- flow integration: #315 and successors
- vector/property embedding: #240 and successors
- targeted client/test fixes: #323/#329/#342 and successors
```

Exit criteria:

- `.workflow/quality-program/checkpoints/00-preflight.md` exists.
- Current CI/test matrix is documented.
- PR collision list is current.
- No production code has been edited.

## G0 Baseline and Test Taxonomy

Purpose: establish an accurate quality map before behavior changes.

Tasks:

1. Add strict pytest markers.
2. Add or normalize test selection docs.
3. Generate coverage baseline without enforcing high thresholds.
4. Enumerate existing skips, xfails, service dependencies, and tests that define local fake production classes.
5. Add a simple `tests/README.md` or `docs/quality/test-taxonomy.md` explaining layers.

Commands should include:

```bash
uv sync --extra dev --extra python-client --extra llm
uv run ruff format --check .
uv run ruff check .
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" --cov=pyhugegraph --cov-report=term --cov-report=json:.workflow/quality-program/coverage/client-baseline.json
uv run pytest hugegraph-llm/src/tests -m "unit or contract" --cov=hugegraph_llm --cov-report=term --cov-report=json:.workflow/quality-program/coverage/llm-baseline.json
```

If markers are not yet fully assigned, first run collection-only and add markers in small batches.

Exit criteria:

- Markers exist and `--strict-markers` works.
- Layer A tests are selectable.
- Baseline coverage files exist.
- Current failures/skips are documented.

## G1 Test Harness and HugeGraph Service Standardization

Purpose: prevent flaky or misleading integration tests before expanding them.

Tasks:

1. Replace blind sleeps in CI with service containers or health-check loops.
2. Standardize HugeGraph version to 1.7.0 for both client and LLM boundary tests unless a documented compatibility matrix is intentionally added.
3. Add shared HugeGraph availability helper with explicit fail/skip semantics.
4. Add graph cleanup fixtures.
5. Ensure `hugegraph-llm` test setup does not globally force all external-service tests to skip when real HugeGraph integration is selected.

Exit criteria:

- `HUGEGRAPH_REQUIRED=true` causes unavailable service to fail selected integration tests.
- Layer B test command is documented and deterministic.
- Existing unit tests still do not require Docker.

## G2 pyhugegraph Contract Hardening

Purpose: make `hugegraph-python-client` a reliable foundation.

Coverage targets:

- schema CRUD: propertyKey, vertexLabel, edgeLabel, indexLabel;
- graph CRUD: add/get/update/delete vertex and edge;
- ID behavior: primary key, numeric ID, custom string ID;
- Gremlin: primitive result, vertex/edge result, empty result, invalid/security errors;
- auth/graphspace: route construction and error surfaces;
- response validation: data envelope, backend error envelope, malformed response, no swallowed connection errors.

Allowed production fixes:

- response parsing,
- explicit exception mapping,
- route construction,
- graphspace/auth routing,
- deterministic fixture cleanup.

Forbidden:

- public API rename,
- HTTP layer replacement,
- broad data class rewrites,
- unrelated format-only changes.

Exit criteria:

- Layer A client tests pass.
- Layer B client contract tests pass against HugeGraph 1.7.0.
- Each production change is listed in `production-change-ledger.md` with a test proving it.

## G3 `hugegraph-llm` HugeGraph Boundary Hardening

Purpose: verify LLM-side schema/read/write/Gremlin boundaries against real HugeGraph.

Primary files:

```text
hugegraph-llm/src/hugegraph_llm/operators/hugegraph_op/
hugegraph-llm/src/hugegraph_llm/nodes/hugegraph_node/
hugegraph-llm/src/hugegraph_llm/utils/hugegraph_utils.py
hugegraph-llm/src/tests/operators/hugegraph_op/
hugegraph-llm/src/tests/integration/
```

Required tests:

1. `SchemaManager` reads real schema and returns expected full/simple schema.
2. `Commit2Graph` creates schema, writes vertices/edges, and readback matches expected counts and endpoints.
3. `FetchGraphData` returns stable counts and ID samples.
4. Gremlin execution surfaces server/client failures explicitly.
5. Vertex ID and edge endpoint behavior matches pyhugegraph contract.
6. Creation failure paths do not become `NoneType.id` secondary errors; tests must assert the intended explicit failure contract.

Exit criteria:

- Mock-only tests are not the only proof for write/read behavior.
- Failures are classified as service setup, client contract, server contract, or LLM conversion.
- No real LLM provider dependency is introduced.

## G4 Parser / API / Operator Deterministic Contract Coverage

Purpose: make recent bug-prone pure logic paths deterministic and high-signal.

Targets:

- graph JSON parsing robustness,
- keyword extraction output parser,
- property graph extraction normalization,
- Gremlin-only output contract,
- API request/response models,
- config endpoint field mapping,
- provider wrapper error wrapping,
- reranker and embedding failure surfaces,
- empty inputs and malformed/adversarial provider outputs.

Required rules:

- Use fake LLMs and mocked SDK calls.
- Use FastAPI public surface for endpoint behavior.
- Test invalid input and error surface, not only happy paths.
- Do not make real external calls.

Exit criteria:

- Parser/API/operator local coverage materially improves.
- Each parser production fix has adversarial/malformed regression tests.
- API tests cover public models or endpoints.

## G5 Core RAG / KG / Text2Gremlin Smoke Gates

Purpose: replace fake integration tests with smoke tests that import production code while keeping intelligence deterministic.

Required smoke tests:

### KG Construction Smoke

- Fixture text.
- Fake LLM graph output.
- Production graph extraction/normalization.
- Commit to real HugeGraph when marked Layer C+B.
- Read back expected vertex/edge count and selected properties.

### GraphRAG Smoke

- Fixture graph/doc.
- Deterministic embedding/vector fixture.
- Production retrieval path.
- Structured evidence returned.
- No real LLM provider call.

### Text2Gremlin Smoke

- Fixture schema.
- Fake LLM Gremlin output.
- Gremlin-only contract normalization.
- Optional execution against HugeGraph.

Anti-patterns:

- Do not define `RAGPipeline`, `KGConstructor`, or `OpenAILLM` replacement classes inside integration tests.
- Do not validate only that mocks were called.
- Do not require external provider credentials.

Exit criteria:

- Smoke tests run deterministically.
- Existing mock-only integration tests are either converted, downgraded to unit tests, or documented as weak tests with a replacement path.

## G6 Coverage Ratchet and CI Split

Purpose: convert test signal into durable quality gates.

Ratchet rules:

1. Start with local module/area thresholds, not a global repo threshold.
2. New production logic requires tests.
3. Bug fixes require regression tests.
4. HugeGraph boundaries need Layer B or Layer C evidence.
5. Thresholds may be low initially but must not decrease.
6. Store JSON coverage reports and compare them to baseline.

Suggested local ratchet areas:

- `pyhugegraph`,
- `hugegraph_llm.operators.hugegraph_op`,
- `hugegraph_llm.operators.llm_op` parser modules,
- `hugegraph_llm.api` and `hugegraph_llm.api.models`.

CI split:

```text
client-unit-contract
client-hugegraph-integration
llm-unit-contract
llm-hugegraph-boundary
llm-core-smoke
ruff-format-check
ruff-lint-check
optional-external-nightly
```

Exit criteria:

- CI reports layers separately.
- Coverage artifacts are uploaded.
- Failures localize to one layer.
- No high full-repo threshold is introduced in one jump.

## G7 Deferred Refactor Queue

Each deferred item must include:

```text
- title
- blocked_by PR or condition
- affected modules
- why deferred
- prerequisite tests
- trigger condition for future work
- suggested future goal
```

Required deferred items:

1. Async/streaming API full-chain refactor.
2. YAML config migration and config consolidation.
3. Demo UI decomposition.
4. Flow/node/operator boundary redesign.
5. Vector DB backend abstraction cleanup.
6. Broader dependency/config cleanup.
7. Optional MCP/tool-surface integration if relevant open PRs land.

Exit criteria:

- Deferred queue exists in docs or `.workflow/quality-program/reports/deferred-refactors.md`.
- Current task did not execute deferred refactors.

## Final Deliverables

1. Test taxonomy and marker definitions.
2. CI/test matrix documentation.
3. Coverage baselines and ratchets.
4. Real HugeGraph contract tests for pyhugegraph.
5. Real HugeGraph boundary tests for `hugegraph-llm`.
6. Deterministic parser/API/operator tests.
7. Production-code change ledger with regression tests.
8. Core KG/GraphRAG/Text2Gremlin smoke gates using production code.
9. Deferred refactor queue.
10. Final quality report with commands, failures, skipped tests, known risks, and next actions.

## Codex `/goal` Prompt Skeleton

```text
/goal Execute the HugeGraph AI Quality Program v2 for apache/hugegraph-ai.

Primary objective:
  Improve test effectiveness, service-boundary confidence, deterministic parser/API/operator coverage,
  and CI quality gates without broad refactors.

Execution mode:
  Long-running, unattended, restartable. Maintain `.workflow/quality-program/quality-state.json`
  and a checkpoint markdown after every goal.

Mandatory preflight:
  1. Read AGENTS.md, hugegraph-llm/AGENTS.md, and rules/README.md.
  2. Snapshot open PRs and quarantine collision zones.
  3. Inspect current CI, pytest config, conftest skip behavior, Docker image versions, and test layout.
  4. Do not edit production code before preflight is recorded.

Goal order:
  P0. Repository recon and collision gate
  G0. Baseline and test taxonomy
  G1. HugeGraph service fixture and CI standardization
  G2. pyhugegraph contract hardening
  G3. hugegraph-llm HugeGraph boundary hardening
  G4. parser/API/operator deterministic contract coverage
  G5. KG/GraphRAG/Text2Gremlin core smoke gates
  G6. coverage ratchet and CI split
  G7. deferred refactor queue and final report

Hard constraints:
  - Use HugeGraph 1.7.0 for Layer B unless explicitly documenting a compatibility matrix.
  - Do not silently skip required service failures.
  - Do not require real LLM/embedding/reranker/vector DB credentials outside Layer D.
  - Do not perform async/streaming full-chain refactor.
  - Do not perform YAML config migration.
  - Do not decompose demo UI.
  - Do not redesign flow/node/operator boundaries.
  - Do not make broad style-only rewrites.
  - Every production change must have a regression, contract, or integration test.
  - Integration tests must import production code; do not define local fake production pipeline classes.

Checkpoint after each goal:
  - files touched
  - tests added/changed
  - production changes
  - commands run
  - failures observed
  - skips/xfails observed
  - coverage artifacts
  - deferred items
  - readiness for next goal

Abort/pause if:
  - open PR collision affects the same file set,
  - selected required service tests cannot reach HugeGraph,
  - a proposed fix crosses a deferred-refactor boundary,
  - tests are only improving coverage numbers without behavior signal,
  - failure classification is unclear after focused investigation.

Final output:
  Produce `.workflow/quality-program/reports/final-quality-report.md` summarizing the full test matrix,
  coverage baseline/ratchet, production change ledger, commands run, remaining risks, and future work.
```
