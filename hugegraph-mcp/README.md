# HugeGraph MCP

[中文文档](README.zh-CN.md)

HugeGraph MCP is a Model Context Protocol server for HugeGraph. V1 is designed as a safe, controlled, thin adapter layer: it exposes a small set of stable tools and centralizes configuration, permission checks, read-only Gremlin validation, the dry-run/confirm write safety chain, and the unified response envelope.

**Requires HugeGraph Server >= 1.7.0** (MCP defaults to `graphspace=DEFAULT` and relies on graphspace-scoped API routes that are not available in older versions).

## Developer Notes

### Design Boundary

V1 does not turn MCP into a second business kernel. The MCP layer is responsible for:

- Exposing stable MCP tool interfaces
- Reading runtime configuration
- Enforcing permission and readonly guards
- Validating whether Gremlin is read-only
- Generating and validating `plan_hash`
- Returning a unified response envelope
- Forwarding AI capabilities to HugeGraph-AI, or graph reads/writes to HugeGraph Server

### Public Tool Surface

V1 exposes these stable tools to users:

- `inspect_graph_tool`
- `generate_gremlin_tool`
- `execute_gremlin_read_tool`
- `extract_graph_data_tool`
- `import_graph_data_tool`
- `delete_graph_data_tool`
- `design_schema_tool`
- `apply_schema_tool`

These tools are still registered in MCP, but they are admin/debug capabilities and are blocked by default when `HUGEGRAPH_MCP_ADMIN_MODE=false`. Write-capable admin tools also require `HUGEGRAPH_MCP_READONLY=false`:

- `execute_gremlin_write_tool`
- `refresh_vid_embeddings_tool`

### Unified Response Envelope

V1 high-level tools return a unified envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "warnings": [],
  "next_actions": [],
  "meta": {
    "request_id": "req-...",
    "graph": "hugegraph",
    "graphspace": "DEFAULT",
    "readonly": true,
    "duration_ms": 12.3
  }
}
```

When a call fails, `ok=false` and `error` uses this structure:

```json
{
  "type": "READONLY_VIOLATION",
  "message": "DATA_WRITE capability is disabled in read-only mode",
  "suggestion": "Disable HUGEGRAPH_MCP_READONLY to allow this operation.",
  "retryable": false,
  "source": "hugegraph-mcp",
  "details": {}
}
```

## Tool Reference

### User-Facing Tool Overview

| Tool | Description |
|------|-------------|
| `inspect_graph_tool` | Inspect HugeGraph Server status, schema summary, vertex/edge counts, readonly state, and AI availability |
| `generate_gremlin_tool` | Generate Gremlin from natural language; defaults to generation only; `execute=true` still requires read-only validation |
| `execute_gremlin_read_tool` | Execute read-only Gremlin queries; rejects queries whose safety cannot be confirmed |
| `extract_graph_data_tool` | Extract candidate graph data from natural language text and return vertex/edge structures without writing to HugeGraph |
| `import_graph_data_tool` | Structured graph data import entrypoint; real writes must pass `dry_run -> plan_hash -> confirm` |
| `delete_graph_data_tool` | Controlled delete entrypoint; supports only exact vertex or edge deletion, not conditional bulk delete or cascade delete |
| `design_schema_tool` | Provide schema design guidance from proposed schema operations without modifying the database |
| `apply_schema_tool` | V1 supports only schema `validate` and `dry_run`; real `apply` is currently disabled |
| `execute_gremlin_write_tool` | Execute direct Gremlin writes; disabled by default and available only when `HUGEGRAPH_MCP_ADMIN_MODE=true` and `HUGEGRAPH_MCP_READONLY=false` |
| `refresh_vid_embeddings_tool` | Refresh VID embeddings and mutate index state; disabled by default and available only when `HUGEGRAPH_MCP_ADMIN_MODE=true` and `HUGEGRAPH_MCP_READONLY=false` |

The old `query_graph_tool`, `manage_schema_tool`, and `manage_graph_data_tool` are no longer exposed as user interfaces. New integrations should use the stable tools listed above.

## Write Safety Chain

All user-reachable write operations must follow this chain:

```text
dry_run=true
  -> user/agent reviews preview, warnings, matched_count, mutation_summary
  -> records plan_hash, nonce, expires_at
  -> dry_run=false + confirm=true + original payload + plan_hash + nonce + expires_at
  -> MCP revalidates target, permission, schema, payload digest, and expiry
  -> executes the write
  -> returns write/delete results and failure details
```

`plan_hash` is not just a payload hash. It binds at least:

- Tool name
- Operation mode
- Graph URL
- Graph name
- Graph space
- Permission state such as readonly/admin flags
- Current schema hash
- Normalized payload digest
- Nonce
- Expiry

The confirm phase must fully revalidate the plan. If the dry-run result expires, the target graph changes, the schema changes, the payload changes, or permissions change, confirm must fail and require a new dry run.

### Import Semantics

`import_graph_data_tool(mode="ingest")` is the public MCP V1 structured import path. It uses local schema validation, dry-run/hash/confirm, and direct Gremlin writes through `manage_graph_data()`; it does not call the HugeGraph-AI `/graph-import` HTTP path. The legacy/internal AI-backed function is named `ingest_graph_data_via_ai()`.

When `import_graph_data_tool(mode="ingest")` executes a create operation, it returns one of three states:

- `success`: all writes succeeded
- `partial` / `degraded`: some writes succeeded, some failed, or the final state cannot be fully confirmed
- `error`: the write failed

The response should include written counts, failure details, and compensation suggestions to avoid an untraceable partial write.

#### Edge Endpoint Contract

Edge endpoints accept both object and scalar forms:

```text
object source/target  -> forwarded as-is
  {"id": "1:Alice"}   -> HugeGraph vertex id match
  {"name": "Alice"}   -> primary-key/property match

scalar source/target  -> if the live schema says the endpoint label has exactly
                         one primary key, match by that primary key first;
                         otherwise fall back to {"id": value}

outV / inV / vertex id in payload -> always HugeGraph vertex id, with no
                                     primary-key remapping
```

The scalar endpoint form is a same-payload import convenience, but under a single-primary-key live schema it is resolved as a primary-key match and may match an already existing vertex in the graph. It is not limited to vertices in the current payload, so edge-only or edge-to-existing-vertex payloads are valid when the dry-run live match resolves each endpoint to exactly one vertex.

### Delete Semantics

`delete_graph_data_tool` is a controlled delete tool:

- The dry-run phase must resolve the concrete objects that would be deleted
- The confirm phase must re-match and verify that the target is unchanged
- The tool must verify after deletion that the target no longer exists
- Vertex deletion is rejected by default when the vertex has associated edges

Therefore, when deleting a vertex with associated edges, explicitly dry-run and delete the related edges first, then dry-run and delete the vertex.

## Configuration

All configuration is read from environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server URL |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | Graph path in `GRAPH_SPACE/GRAPH_NAME` format |
| `HUGEGRAPH_GRAPHSPACE` | unset | Override graph space separately |
| `HUGEGRAPH_GRAPH` | unset | Override graph name separately |
| `HUGEGRAPH_USER` | `admin` | HugeGraph username |
| `HUGEGRAPH_PASSWORD` | `""` | HugeGraph password |
| `HUGEGRAPH_MCP_READONLY` | `true` | Whether readonly mode is enabled |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | Whether HugeGraph-AI calls are allowed |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | Whether admin/debug tools are enabled |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI URL |
| `HUGEGRAPH_AI_GRAPH_URL` | unset | Graph URL used by HugeGraph-AI; defaults to `HUGEGRAPH_URL` when unset |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | AI call timeout in seconds |
| `HUGEGRAPH_MCP_MAX_REPEAT_TIMES` | `10` | Recommended maximum for read-cost warnings on `repeat().times(n)` |

`HUGEGRAPH_MCP_TIMEOUT_SECONDS` only applies to HugeGraph-AI HTTP calls; it does not apply to PyHugeClient Gremlin queries. Read-only Gremlin cost boundaries are reported as non-blocking read cost guard warnings for bare full-graph scans, `repeat()` without a `times()` bound, and `path` / `group` / `profile` without `limit` or `range`.

Recommended safe defaults:

- `HUGEGRAPH_MCP_READONLY=true`
- `HUGEGRAPH_MCP_ALLOW_AI=false`
- `HUGEGRAPH_MCP_ADMIN_MODE=false`

Common combinations:

| Scenario | Configuration |
|----------|---------------|
| Read-only graph query | `READONLY=true`, `ALLOW_AI=false` |
| AI Gremlin generation / text extraction | `READONLY=true`, `ALLOW_AI=true` |
| Controlled import and delete | `READONLY=false`, set `ALLOW_AI=true` as needed |
| Administration/debugging | `READONLY=false`, `ADMIN_MODE=true` |

## License

Apache License 2.0
