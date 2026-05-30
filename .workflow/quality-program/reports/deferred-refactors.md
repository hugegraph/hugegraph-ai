# Deferred Refactors

## Async/Streaming API Full-Chain Refactor

- blocked_by: `#179` or successor PR status
- affected modules: `hugegraph-llm/src/hugegraph_llm/api/`, flows, nodes, streaming response paths
- why deferred: broad async contract collision and explicitly outside the quality-program scope
- prerequisite tests: parser/API contract tests, core smoke tests, selected streaming boundary tests
- trigger condition: upstream async/streaming PR merged, closed, or superseded with a stable API contract
- suggested future goal: async/streaming boundary and smoke gate

## YAML Config Migration

- blocked_by: `#350`, `#277`, or successor config migration work
- affected modules: config loading, generated config defaults, API config endpoints, tests that assume current config layout
- why deferred: migration would replace configuration contracts instead of testing current behavior
- prerequisite tests: current config unit contracts, API config endpoint tests, compatibility tests for old and new config shapes
- trigger condition: maintainers choose the migration direction and settle replacement/deprecation behavior
- suggested future goal: config compatibility ratchet and migration smoke gate

## Demo UI Decomposition

- blocked_by: UI ownership and decomposition scope not part of Layer A-C quality gates
- affected modules: demo UI, generated/static assets, browser-facing flows
- why deferred: would require UI-specific review and assets beyond deterministic backend quality gates
- prerequisite tests: API contracts for UI calls, focused browser smoke tests with deterministic backend fixtures
- trigger condition: UI decomposition work is accepted as a separate feature or maintenance goal
- suggested future goal: UI contract smoke and static asset verification

## Flow/Node/Operator Boundary Redesign

- blocked_by: `#315` or successor flow integration redesign
- affected modules: `hugegraph-llm/src/hugegraph_llm/flows/`, nodes, operators, operator return contracts
- why deferred: redesigning execution architecture is beyond test hardening and risks invalidating current smoke evidence
- prerequisite tests: current operator contracts, flow smoke tests, graph-boundary integration tests
- trigger condition: a concrete redesign spec is approved and its compatibility requirements are known
- suggested future goal: flow/node/operator contract migration plan

## Vector DB Backend Abstraction Cleanup

- blocked_by: `#240` or successor vector/property embedding abstraction work
- affected modules: vector index, embedding provider adapters, retrievers, rerank paths
- why deferred: broad backend abstraction cleanup could require live service credentials and provider-specific semantics
- prerequisite tests: deterministic vector index contracts, provider wrapper error-surface tests, optional Layer D live backend checks
- trigger condition: target backend abstraction and supported providers are explicitly chosen
- suggested future goal: vector backend compatibility matrix and Layer D provider workflow

## Broader Dependency and Config Cleanup

- blocked_by: dependency replacement decisions and config migration direction
- affected modules: root `pyproject.toml`, module `pyproject.toml` files, lockfile, CI install paths
- why deferred: dependency/config replacement can alter the whole workspace and is not necessary for this quality gate
- prerequisite tests: full unit/contract matrix, selected HugeGraph integration, import/collection checks
- trigger condition: dependency replacement is tied to a concrete failing test or accepted maintenance issue
- suggested future goal: dependency update branch with import and runtime compatibility checks

## Optional MCP and Tool-Surface Integration

- blocked_by: unclear public contract and likely external service requirements
- affected modules: MCP/tool server surfaces, agent-facing integration points
- why deferred: external tool-surface behavior belongs outside default PR gates until a stable contract exists
- prerequisite tests: deterministic command/tool contract tests, fake transport tests, optional live integration workflow
- trigger condition: maintainers define supported MCP/tool APIs and credentials model
- suggested future goal: MCP/tool contract test suite and opt-in live smoke
