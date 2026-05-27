# HugeGraph MCP

[中文文档](README.zh-CN.md)

FastMCP-based Model Context Protocol server for HugeGraph. It lets AI assistants inspect graph status, generate and run read-only Gremlin, extract candidate graph data, and design or preview schema changes through a small set of V1 stable tools.

## Quick Start

### Prerequisites

- HugeGraph Server, for example `http://127.0.0.1:8080`, version 1.7.0 or later
- Python 3.10+
- Git in `PATH`

### MCP Configuration

Add an MCP server entry to your IDE or assistant MCP configuration file:

```json
{
  "mcpServers": {
    "hugegraph-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/hugegraph/hugegraph-ai.git@graph-mcp#subdirectory=hugegraph-mcp",
        "hugegraph-mcp"
      ],
      "env": {
        "HUGEGRAPH_MCP_READONLY": "true"
      }
    }
  }
}
```

Restart your IDE or assistant after adding the configuration.

### Optional Environment Variables

All environment variables are optional:

- `HUGEGRAPH_URL` (default: `http://127.0.0.1:8080`)
- `HUGEGRAPH_GRAPH_PATH` (default: `DEFAULT/hugegraph`)
- `HUGEGRAPH_USER` (default: `admin`)
- `HUGEGRAPH_PASSWORD` (default: empty string)
- `HUGEGRAPH_MCP_READONLY` (default: `true`)
- `HUGEGRAPH_MCP_ALLOW_AI` (default: `false`)
- `HUGEGRAPH_MCP_ADMIN_MODE` (default: `false`)
- `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL` (default: `false`)
- `HUGEGRAPH_MCP_SQL_ENABLED` (default: `false`)
- `HUGEGRAPH_AI_URL` (default: `http://127.0.0.1:8001`)
- `HUGEGRAPH_AI_GRAPH_URL` (default: unset)
- `HUGEGRAPH_MCP_TIMEOUT_SECONDS` (default: `30`)
- `HUGEGRAPH_MCP_MAX_CONTEXT_ITEMS` (default: `100`)

`HUGEGRAPH_GRAPH_PATH` uses the format `GRAPH_SPACE/GRAPH_NAME`, for example `DEFAULT/hugegraph`.

`HUGEGRAPH_MCP_READONLY` and `HUGEGRAPH_MCP_ALLOW_AI` are controlled independently:

- `HUGEGRAPH_MCP_READONLY=true` blocks mutating schema, graph data, index, and direct write operations.
- `HUGEGRAPH_MCP_ALLOW_AI=true` allows calls to HugeGraph-AI, including natural-language Gremlin generation and graph data extraction.
- `HUGEGRAPH_MCP_READONLY=false` enables write-capable paths that are otherwise blocked by readonly mode.
- `HUGEGRAPH_MCP_ADMIN_MODE=true` enables admin/debug tools such as direct Gremlin writes and embedding refresh.
- `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=true` enables the experimental GraphRAG text-query path for debugging. It is disabled by default and is not the primary user query path.
- You can set both to `true` to allow AI-assisted read/query/extraction workflows while still blocking all writes.

Safe V1 defaults are `readonly=true`, `allow_ai=false`, and `sql_enabled=false`.

If first-run dependency installation is slow, pre-install the MCP server locally:

```bash
uvx --from git+https://github.com/hugegraph/hugegraph-ai.git@graph-mcp#subdirectory=hugegraph-mcp hugegraph-mcp
```

Then restart your IDE or assistant.

## Main Tools

V1 stable tools return the unified envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "warnings": [],
  "next_actions": [],
  "meta": {
    "request_id": "...",
    "graph": "hugegraph",
    "graphspace": "DEFAULT",
    "readonly": true,
    "duration_ms": 0
  }
}
```

### V1 Stable Tool List

These are the stable public V1 tools:

| Tool | Description |
| --- | --- |
| `inspect_graph_tool` | Inspect HugeGraph Server status, schema summary, counts, readonly state, and AI availability. |
| `generate_gremlin_tool` | Convert natural language to Gremlin through HugeGraph-AI. Defaults to generation only; set `execute=true` to run safe read-only Gremlin. |
| `execute_gremlin_read_tool` | Execute a Gremlin traversal after read-only policy validation. |
| `extract_graph_data_tool` | Extract candidate `{vertices, edges}` graph data from text. It does not write to HugeGraph. |
| `import_graph_data_tool` | Import structured graph data through MCP local validation, dry-run/confirm, and Gremlin execution. |
| `design_schema_tool` | Get schema design guidance from proposed operations. |
| `apply_schema_tool` | Validate or dry-run schema operations. `mode="apply"` is disabled in V1. |

The old multi-mode compatibility tools are not exposed in V1. Use the stable tools above directly.

### 1. Inspect Graph Status And Schema

Use `inspect_graph_tool` first after connecting. It checks HugeGraph Server status, HugeGraph-AI availability, schema summary, graph counts, index counts, readonly state, warnings, and suggested next actions. It is best-effort: if part of the backend is unavailable, it returns a degraded envelope instead of failing the whole inspection.

Basic inspection:

```json
{
  "tool": "inspect_graph_tool",
  "arguments": {
    "include_raw_schema": false
  }
}
```

Include the full raw schema when planning schema changes or debugging mismatches:

```json
{
  "tool": "inspect_graph_tool",
  "arguments": {
    "include_raw_schema": true
  }
}
```

### 2. Query The Graph

Use `generate_gremlin_tool` for natural-language Gremlin generation and
`execute_gremlin_read_tool` for known-safe read-only traversals. GraphRAG text
query mode is not exposed in V1.

Generate Gremlin without executing it:

```json
{
  "tool": "generate_gremlin_tool",
  "arguments": {
    "query": "Find the top 10 people with the most outgoing knows edges"
  }
}
```

Generate Gremlin and execute it only if the generated traversal is read-only:

```json
{
  "tool": "generate_gremlin_tool",
  "arguments": {
    "query": "Count person vertices by city",
    "execute": true
  }
}
```

Run a direct read-only Gremlin traversal:

```json
{
  "tool": "execute_gremlin_read_tool",
  "arguments": {
    "gremlin_query": "g.V().hasLabel('person').limit(10).valueMap(true)"
  }
}
```

### 3. Design And Manage Schema

Use `design_schema_tool` for design guidance and `apply_schema_tool` for schema
validation and dry-run previews. Full schema apply is disabled in V1 and
returns `FEATURE_DISABLED`.

Ask for schema design guidance:

```json
{
  "tool": "design_schema_tool",
  "arguments": {
    "operations": []
  }
}
```

Validate operations before planning an apply:

```json
{
  "tool": "apply_schema_tool",
  "arguments": {
    "mode": "validate",
    "operations": [
      {
        "type": "create_property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_vertex_label",
        "name": "person",
        "properties": ["name"],
        "primary_keys": ["name"]
      }
    ]
  }
}
```

Create a dry-run plan and capture the returned `plan_hash`:

```json
{
  "tool": "apply_schema_tool",
  "arguments": {
    "mode": "dry_run",
    "operations": [
      {
        "type": "create_property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_vertex_label",
        "name": "person",
        "properties": ["name"],
        "primary_keys": ["name"]
      }
    ]
  }
}
```

`mode="apply"` is reserved for a later release. In V1, use `mode="dry_run"` to preview the schema diff and risk warnings.

### 4. Graph Data Extraction And Import

Use `extract_graph_data_tool` for graph-shaped extraction from text. Use
`import_graph_data_tool(mode="ingest")` as the single public structured write
entrypoint. V1 disables table import, SQL import, update, and delete.

Structured writes are executed by MCP through its local
`graph_data -> change_plan -> Gremlin` path after schema validation,
`dry_run`, target-bound `plan_hash`, and `confirm=true`. The HugeGraph-AI
`/graph-import` API is not used as a public write path.

Extract candidate graph data from text without writing to HugeGraph:

```json
{
  "tool": "extract_graph_data_tool",
  "arguments": {
    "text": "Alice works at Acme. Bob knows Alice."
  }
}
```

The `schema` argument is optional. In normal usage, omit it so HugeGraph-AI can use the current graph schema. If you pass `schema`, provide a backend-compatible live schema shape instead of a simplified label list.

Dry-run a structured graph data import:

```json
{
  "tool": "import_graph_data_tool",
  "arguments": {
    "mode": "ingest",
    "dry_run": true,
    "graph_data": {
      "vertices": [
        {"label": "person", "id": "alice", "properties": {"name": "Alice"}},
        {"label": "person", "id": "bob", "properties": {"name": "Bob"}}
      ],
      "edges": [
        {
          "label": "knows",
          "source_label": "person",
          "target_label": "person",
          "source": {"name": "Bob"},
          "target": {"name": "Alice"},
          "properties": {}
        }
      ]
    }
  }
}
```

Apply the exact dry-run import plan:

```json
{
  "tool": "import_graph_data_tool",
  "arguments": {
    "mode": "ingest",
    "dry_run": false,
    "confirm": true,
    "plan_hash": "PLAN_HASH_FROM_DRY_RUN",
    "graph_data": {
      "vertices": [
        {"label": "person", "id": "alice", "properties": {"name": "Alice"}},
        {"label": "person", "id": "bob", "properties": {"name": "Bob"}}
      ],
      "edges": [
        {
          "label": "knows",
          "source_label": "person",
          "target_label": "person",
          "source": {"name": "Bob"},
          "target": {"name": "Alice"},
          "properties": {}
        }
      ]
    }
  }
}
```

Table, SQL, update, and delete workflows are planned for a later release. In V1,
use `extract_graph_data_tool` for extraction and
`import_graph_data_tool(mode="ingest")` for structured writes.

## Advanced Debug Tools

These tools are available for maintenance and debugging. Prefer the V1 stable tools for normal workflows.

### `execute_gremlin_write_tool`

Runs a direct Gremlin write query. Prefer `import_graph_data_tool` with
`mode="ingest"` for normal graph data writes because it validates data and uses
the dry-run safety chain.

```json
{
  "tool": "execute_gremlin_write_tool",
  "arguments": {
    "gremlin_query": "g.addV('person').property('name', 'Alice')"
  }
}
```

### `refresh_vid_embeddings_tool`

Refreshes VID embeddings through HugeGraph-AI. This is a mutating index operation and requires explicit confirmation.

```json
{
  "tool": "refresh_vid_embeddings_tool",
  "arguments": {
    "confirm": true
  }
}
```

## Permission Model

The MCP server uses environment switches plus runtime capability guards. It does not provide per-user RBAC.

`HUGEGRAPH_MCP_READONLY` and `HUGEGRAPH_MCP_ALLOW_AI` are intentionally independent:

- `HUGEGRAPH_MCP_READONLY=true` blocks graph-side mutations.
- `HUGEGRAPH_MCP_ALLOW_AI=true` allows HugeGraph-AI calls for natural-language query generation and graph data extraction.
- `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=true` additionally exposes the experimental GraphRAG text-query path for debugging.
- Setting both to `true` allows AI-assisted read/query/extraction workflows while still rejecting graph writes.

| Capability | Used By | `readonly=true` Behavior |
| --- | --- | --- |
| `READ` | Graph status, schema inspection, direct read-only graph queries | Allowed |
| `GENERATE` | Generation-only planning paths | Allowed |
| `DATA_WRITE` | Graph data import, update, and delete apply paths | Rejected |
| `SCHEMA_WRITE` | Schema apply paths | Rejected |
| `INDEX_WRITE` | VID embedding refresh | Rejected |
| `DEBUG_WRITE` | Direct Gremlin write debugging tool | Rejected |

Tool behavior under this model:

| Tool | Behavior |
| --- | --- |
| `inspect_graph_tool` | Always allowed. Returns graph status, schema summary, counts when available, and AI status. |
| `generate_gremlin_tool` | AI-backed Gremlin generation requires `HUGEGRAPH_MCP_ALLOW_AI=true`; execution is still read-only. |
| `execute_gremlin_read_tool` | Read-only Gremlin execution is allowed after policy validation. |
| `extract_graph_data_tool` | AI-backed graph-data extraction requires `HUGEGRAPH_MCP_ALLOW_AI=true`; it does not write. |
| `design_schema_tool` | Schema design guidance is allowed. |
| `apply_schema_tool` | Schema validation and dry runs are allowed; apply is disabled in V1. |
| `import_graph_data_tool` | Single public structured graph-data write entrypoint. Uses MCP local validation, dry-run/confirm, and Gremlin execution. |
| `refresh_vid_embeddings_tool` | Requires `readonly=false` and `confirm=true`. |
| `execute_gremlin_write_tool` | Requires `readonly=false`. Intended for debugging and admin maintenance, not routine data loading. |

V1 disabled capabilities return `FEATURE_DISABLED` instead of executing:

- SQL modes and SQL-backed import (`sql_preview`, `sql_mapping_suggest`, `sql_import`)
- Table import
- Graph data update/delete modes
- Direct debug writes unless `HUGEGRAPH_MCP_ADMIN_MODE=true`
- Refreshing VID embeddings unless `HUGEGRAPH_MCP_ADMIN_MODE=true`
- Full schema apply through `apply_schema_tool`

## Safety Notes

- Set `HUGEGRAPH_MCP_READONLY=true` for exploration, demos, and production read-only assistant access.
- Set `HUGEGRAPH_MCP_ALLOW_AI=true` only when the deployment should call HugeGraph-AI.
- Set `HUGEGRAPH_MCP_READONLY=false` only when writes are intended.
- Set `HUGEGRAPH_MCP_ADMIN_MODE=true` only for maintenance/debug sessions that need admin tools.
- Keep `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=false` for normal user-facing deployments; enable it only while debugging GraphRAG.
- Readonly mode is enforced at runtime for write paths, including graph data import confirmation, direct write queries, and embedding refresh.
- Graph data import confirmation requires a previous dry run, a matching `plan_hash`, and `confirm=true`.
- `generate_gremlin_tool` does not execute generated Gremlin unless `execute=true`.
- Direct Gremlin reads are allowed only when the traversal can be treated as read-only. Unsafe or uncertain traversals are rejected.
- Do not use direct write debugging tools for routine data loading.

## License

Apache License 2.0
