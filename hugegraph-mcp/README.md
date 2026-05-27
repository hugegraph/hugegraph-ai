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

All high-level tools return the unified envelope:

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
| `design_schema_tool` | Get schema design guidance from proposed operations. |
| `apply_schema_tool` | Validate or dry-run schema operations. `mode="apply"` is disabled in V1. |

Compatibility tools such as `query_graph_tool`, `manage_schema_tool`, `manage_graph_data_tool`, and `import_graph_data_tool` remain available, but new integrations should prefer the V1 stable tools above.

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

Use `query_graph_tool` for graph reads. It exposes two stable user modes:

- `generate`: convert a natural-language question to Gremlin. By default this only generates the traversal and does not execute it.
- `gremlin`: execute a known-safe read-only Gremlin traversal directly.

The old `text` GraphRAG mode is kept as an experimental/debug path behind
`HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=true`. By default, callers should use
`mode="generate"` with `execute=true` for natural-language graph questions.

Generate Gremlin without executing it:

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "generate",
    "query": "Find the top 10 people with the most outgoing knows edges"
  }
}
```

Generate Gremlin and execute it only if the generated traversal is read-only:

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "generate",
    "query": "Count person vertices by city",
    "execute": true
  }
}
```

Run a direct read-only Gremlin traversal:

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "gremlin",
    "gremlin_query": "g.V().hasLabel('person').limit(10).valueMap(true)"
  }
}
```

### 3. Design And Manage Schema

Use `manage_schema_tool` to design, validate, dry-run, and apply schema operations. Mutating schema changes require the safety chain `dry_run -> plan_hash -> confirm`.

Ask for schema design guidance:

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "design"
  }
}
```

Validate operations before planning an apply:

```json
{
  "tool": "manage_schema_tool",
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
  "tool": "manage_schema_tool",
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

Apply the exact dry-run plan:

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "apply",
    "confirm": true,
    "plan_hash": "PLAN_HASH_FROM_DRY_RUN",
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

### 4. Manage Graph Data

Use `manage_graph_data_tool` to extract graph-shaped data from text, import structured graph data, map table rows into graph data, update graph elements, or delete graph elements. Mutating graph data changes require the safety chain `dry_run -> plan_hash -> confirm`.

Extract candidate graph data from text without writing to HugeGraph:

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "extract",
    "text": "Alice works at Acme. Bob knows Alice."
  }
}
```

The `schema` argument is optional. In normal usage, omit it so HugeGraph-AI can use the current graph schema. If you pass `schema`, provide a backend-compatible live schema shape instead of a simplified label list.

Dry-run a structured graph data import:

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "import",
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
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "import",
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

Map table rows into graph data and run the same import safety flow:

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "table",
    "dry_run": true,
    "table_data": {
      "table_name": "employment",
      "columns": ["person_name", "company_name"],
      "rows": [
        ["Alice", "Acme"],
        ["Bob", "Acme"]
      ]
    },
    "mapping": {
      "vertex_mappings": [
        {
          "target_label": "person",
          "column_mapping": {"name": "person_name"},
          "primary_key_columns": ["person_name"]
        },
        {
          "target_label": "company",
          "column_mapping": {"name": "company_name"},
          "primary_key_columns": ["company_name"]
        }
      ],
      "edge_mappings": [
        {
          "target_label": "works_at",
          "source_vertex": {
            "label": "person",
            "primary_key_columns": ["person_name"]
          },
          "target_vertex": {
            "label": "company",
            "primary_key_columns": ["company_name"]
          },
          "column_mapping": {}
        }
      ]
    }
  }
}
```

Update a graph element with a dry run:

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "update",
    "dry_run": true,
    "change_plan": {
      "operations": [
        {
          "op": "update_vertex",
          "label": "person",
          "match": {"name": "Alice"},
          "set": {"age": 31}
        }
      ]
    }
  }
}
```

Delete a graph element with a dry run:

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "delete",
    "dry_run": true,
    "change_plan": {
      "operations": [
        {
          "op": "delete_vertex",
          "label": "person",
          "match": {"name": "Alice"},
          "cascade": false
        }
      ]
    }
  }
}
```

`import_graph_data_tool` remains available for compatibility. Prefer `manage_graph_data_tool` for new workflows.

## Advanced Debug Tools

These tools are available for maintenance and debugging. Prefer the V1 stable tools for normal workflows.

### `execute_gremlin_write_tool`

Runs a direct Gremlin write query. Prefer `manage_graph_data_tool` with `mode="import"` for normal graph data writes because it validates data and uses the dry-run safety chain.

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
| `query_graph_tool` | Read-only Gremlin execution is allowed. AI-backed Gremlin generation requires `HUGEGRAPH_MCP_ALLOW_AI=true`. GraphRAG text mode is disabled unless `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=true` is also set. |
| `manage_schema_tool` | Compatibility wrapper. Design, validation, and dry runs are allowed; apply is disabled in V1. |
| `manage_graph_data_tool` | Compatibility wrapper. Natural-language extraction and import dry runs are allowed where applicable; table, SQL, update, and delete modes are disabled in V1. |
| `import_graph_data_tool` | Compatibility wrapper for graph data import. Prefer `manage_graph_data_tool` for new workflows. |
| `refresh_vid_embeddings_tool` | Requires `readonly=false` and `confirm=true`. |
| `execute_gremlin_write_tool` | Requires `readonly=false`. Intended for debugging and admin maintenance, not routine data loading. |

V1 disabled capabilities return `FEATURE_DISABLED` instead of executing:

- SQL modes and SQL-backed import (`sql_preview`, `sql_mapping_suggest`, `sql_import`)
- Table import
- Graph data update/delete modes
- Direct debug writes unless `HUGEGRAPH_MCP_ADMIN_MODE=true`
- Refreshing VID embeddings unless `HUGEGRAPH_MCP_ADMIN_MODE=true`
- Full schema apply through `apply_schema_tool` and the compatibility schema apply path

## Safety Notes

- Set `HUGEGRAPH_MCP_READONLY=true` for exploration, demos, and production read-only assistant access.
- Set `HUGEGRAPH_MCP_ALLOW_AI=true` only when the deployment should call HugeGraph-AI.
- Set `HUGEGRAPH_MCP_READONLY=false` only when writes are intended.
- Set `HUGEGRAPH_MCP_ADMIN_MODE=true` only for maintenance/debug sessions that need admin tools.
- Keep `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL=false` for normal user-facing deployments; enable it only while debugging GraphRAG.
- Readonly mode is enforced at runtime for write paths, including schema changes, graph data import/update/delete apply paths, direct write queries, and embedding refresh.
- Schema apply and graph data import/update/delete apply paths require a previous dry run, a matching `plan_hash`, and `confirm=true`.
- `query_graph_tool` with `mode="generate"` does not execute generated Gremlin unless `execute=true`.
- Direct Gremlin reads are allowed only when the traversal can be treated as read-only. Unsafe or uncertain traversals are rejected.
- Do not use direct write debugging tools for routine data loading.

## License

Apache License 2.0
