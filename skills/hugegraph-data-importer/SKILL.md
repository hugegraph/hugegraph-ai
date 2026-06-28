---
name: hugegraph-data-importer
description: Route HugeGraph MCP V1 graph data extraction and import tasks to stable public tools. Use when the user asks to extract graph data from text, import structured vertices or edges, verify an import, or asks whether table, SQL, update, or delete graph writes are available.
---

# HugeGraph Data Importer

## Tool Routes

| Goal | Tool |
| --- | --- |
| Inspect schema, primary keys, or edge endpoints | `inspect_graph_tool(include_raw_schema=true)` |
| Extract candidate graph data from text | `extract_graph_data_tool(text, schema?, example_prompt?)` |
| Preview structured vertex/edge import | `import_graph_data_tool(mode="ingest", graph_data, dry_run=true)` |
| Execute confirmed import | `import_graph_data_tool(mode="ingest", graph_data, dry_run=false, confirm=true, plan_hash, nonce, expires_at)` |
| Preview controlled vertex/edge delete | `delete_graph_data_tool(change_plan, dry_run=true)` |
| Execute confirmed controlled delete | `delete_graph_data_tool(change_plan, dry_run=false, confirm=true, plan_hash, nonce, expires_at)` |
| Verify imported data | `execute_gremlin_read_tool(gremlin_query)` |

## Order

```text
inspect_graph_tool -> extract_graph_data_tool or prepare graph_data
-> import_graph_data_tool(dry_run=true)
-> import_graph_data_tool(dry_run=false, confirm=true, plan_hash, nonce, expires_at)
-> execute_gremlin_read_tool
```

For controlled deletes:

```text
inspect_graph_tool(include_raw_schema=true)
-> delete_graph_data_tool(dry_run=true)
-> delete_graph_data_tool(dry_run=false, confirm=true, plan_hash, nonce, expires_at)
-> execute_gremlin_read_tool
```
