# HugeGraph MCP

FastMCP-based Model Context Protocol server for HugeGraph. It lets AI assistants inspect graph status, query graph data, manage schema, and import graph data through a small set of high-level tools.

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
- `HUGEGRAPH_MCP_READONLY` (default: `false`)

`HUGEGRAPH_GRAPH_PATH` uses the format `GRAPH_SPACE/GRAPH_NAME`, for example `DEFAULT/hugegraph`.

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

Use `query_graph_tool` for graph reads. It supports three modes:

- `text`: ask a natural-language question through HugeGraph-AI RAG.
- `generate`: convert a natural-language question to Gremlin. By default this only generates the traversal and does not execute it.
- `gremlin`: execute a known-safe read-only Gremlin traversal directly.

Natural-language graph question:

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "text",
    "query": "Which people does Alice know?",
    "rag_mode": "graph_only",
    "include_evidence": true,
    "max_context_items": 20
  }
}
```

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
        "type": "property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "vertex_label",
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
        "type": "property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "vertex_label",
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
        "type": "property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "vertex_label",
        "name": "person",
        "properties": ["name"],
        "primary_keys": ["name"]
      }
    ]
  }
}
```

### 4. Import Graph Data

Use `import_graph_data_tool` to extract graph-shaped data from text, ingest structured graph data, or map table rows into graph data. Mutating imports require the safety chain `dry_run -> plan_hash -> confirm`.

Extract candidate graph data from text without writing to HugeGraph:

```json
{
  "tool": "import_graph_data_tool",
  "arguments": {
    "mode": "extract",
    "text": "Alice works at Acme. Bob knows Alice.",
    "schema": {
      "vertices": ["person", "company"],
      "edges": ["knows", "works_at"]
    }
  }
}
```

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

Map table rows into graph data and run the same import safety flow:

```json
{
  "tool": "import_graph_data_tool",
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

## Advanced Debug Tools

These tools are available for maintenance and debugging. Prefer the four main tools for normal workflows.

### `execute_gremlin_write_tool`

Runs a direct Gremlin write query. Prefer `import_graph_data_tool` with `mode="ingest"` for normal graph data writes because it validates data and uses the dry-run safety chain.

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

## Safety Notes

- Set `HUGEGRAPH_MCP_READONLY=true` for exploration, demos, and production read-only assistant access.
- Readonly mode is enforced at runtime for write paths, including schema changes, data imports, direct write queries, and embedding refresh.
- Schema apply and data ingest require a previous dry run, a matching `plan_hash`, and `confirm=true`.
- `query_graph_tool` with `mode="generate"` does not execute generated Gremlin unless `execute=true`.
- Direct Gremlin reads are allowed only when the traversal can be treated as read-only. Unsafe or uncertain traversals are rejected.
- Do not use direct write debugging tools for routine data loading.

## License

Apache License 2.0
