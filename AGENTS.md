# AGENTS.md

Guidance for AI agents working in this repository. Keep README content in README files; keep this file focused on decisions agents commonly get wrong.

## Stack & Modules

- This is a Python `uv` workspace. Prefer root-level workspace commands unless a module-specific file says otherwise.
- `hugegraph-llm/` is the primary and most frequently changed module. When editing or reviewing it, read `hugegraph-llm/AGENTS.md` first.
- `hugegraph-python-client/` is a supporting dependency for HugeGraph access. Change it only when the client contract itself must change, and verify `hugegraph-llm` callers when you do.
- Treat `hugegraph-ml/` and `vermeer-python-client/` as lower-frequency modules. Do not expand changes into them without a direct reason.

## Testing Expectations

- Any code change must include sufficient and effective test coverage for the changed behavior, regression risk, or failure path.
- Do not add tests that only improve coverage numbers while mocking away the behavior being changed.
- If a change cannot reasonably include automated tests, state why and provide the manual verification performed.
- Cross-module or shared dependency changes must test the affected downstream module, not only the package where the edit was made.

## Code Search Anchors

- `hugegraph-llm/src/hugegraph_llm/` - main LLM, RAG, KG, prompt, API, and vector-index code.
- `hugegraph-python-client/src/pyhugegraph/` - Python client used by LLM code to talk to HugeGraph.
- `pyproject.toml` and module `pyproject.toml` files - workspace membership, dependency groups, lint settings, Python versions.
- `rules/README.md` - staged AI-assisted workflow for multi-file features, API contract changes, or cross-module design changes.

## Build & Test

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
```

- Run tests for the affected module rather than defaulting to a full-repository test sweep.
- For `hugegraph-llm`, use the module CI split between unit-style tests and integration tests.
- For `hugegraph-python-client`, include client tests and any `hugegraph-llm` tests needed to validate caller compatibility.

## Agent Workflow

- Before editing, identify whether the change belongs to `hugegraph-llm`, `hugegraph-python-client`, or root workspace configuration.
- For multi-file features, API contract changes, or cross-module design changes, read `rules/README.md` first.
- Keep changes scoped to the module that owns the behavior. Avoid opportunistic rewrites in sibling modules.

## Cross-module Notes

- Root dependency or workspace changes can affect multiple packages; verify the package that consumes the changed dependency.
- `hugegraph-llm` imports `hugegraph-python-client`; client API changes must preserve or deliberately update those call sites.
- Do not duplicate README quick-start, Docker, or deployment instructions in AGENTS files.

## MCP V1 Implementation Phase

When working on the `hugegraph-mcp` V1 improvement plan, Codex operates as the **executor** under Claude's orchestration.

### Role definition

| Aspect | Rule |
|--------|------|
| Task source | Only accept tasks explicitly assigned by Claude. Do not self-select or expand scope. |
| Architecture | Do not make architectural decisions independently. Defer uncertain design choices to Claude. |
| Completion | Wait for Claude's review after each task. Do not self-mark tasks as complete. |
| Scope | Implement exactly what the task specifies. No opportunistic rewrites or unrelated cleanup. |

### Implementation standards

- **Unified envelope**: All new high-level tools MUST return `{ ok, data, error: { type, message, suggestion, retryable, source, details }, warnings, next_actions, meta: { request_id, graph, graphspace, readonly, duration_ms } }`.
- **Readonly guard**: Write paths MUST check readonly at runtime, not just at tool registration. `execute_schema_operations` must have a runtime readonly guard.
- **Write safety chain**: Write/schema-apply operations MUST gate on `dry_run → plan_hash → confirm` before execution.
- **Gremlin safety**: `execute_gremlin_read` MUST NOT rely solely on keyword matching to reject write statements. When safety cannot be reliably determined, return `UNSAFE_GREMLIN`.
- **Default password**: Never use `"xxx"` as a real default password in config.
- **Architecture boundary**: MCP does NOT import `hugegraph-llm` flows directly. Always use HTTP to call HugeGraph-AI APIs.
- **Old tools preserved**: Existing tool names are retained. New high-level tools are additive. Old write tools must also pass through runtime guards.

### Testing requirements

- Every implementation task MUST include tests that exercise the changed behavior.
- P0 mandatory test coverage: config parsing, readonly guard enforcement, unified envelope structure, `inspect_graph` degraded behavior, `generate_gremlin` default-no-execute, write-Gremlin rejection.
- Existing tests MUST NOT regress.
- Integration tests use a dedicated test graph or fixture, never the user's production graph.

### Quality bar (before handoff)

- `ruff format --check .` and `ruff check .` pass from the repo root.
- All existing tests still pass.
- No dead code, no placeholder comments, no unexplained TODO markers.

### Handoff format

Every task completion MUST end with:

```text
===HANDOFF===
Completed:
- Item
Pending:
- Item
Decisions:
- Item
Files:
- path (summary)
Risks:
- Item
Questions:
- Item
===END===
```

### Code anchors for MCP work

- `hugegraph-mcp/hugegraph_mcp/server.py` — FastMCP server bootstrap with 5 tools
- `hugegraph-mcp/hugegraph_mcp/gremlin_tools.py` — Gremlin executor and `HugeGraphGremlinConfig`
- `hugegraph-mcp/hugegraph_mcp/schema_tools.py` — Schema design and operations tools
- `hugegraph-mcp/tests/` — Existing test suite
- `hugegraph-python-client/src/pyhugegraph/` — HugeGraph REST client (read-only boundary for MCP)

### Environment

- Python `>=3.10` for `hugegraph-mcp`.
- `hugegraph-mcp` is NOT a uv workspace member; dependencies are managed via its own `pyproject.toml`.
- Run MCP tests: `cd hugegraph-mcp && uv run pytest`.
