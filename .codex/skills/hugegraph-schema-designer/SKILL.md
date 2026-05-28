---
name: hugegraph-schema-designer
description: Route HugeGraph MCP V1 schema design, validation, and dry-run preview tasks to stable public tools. Use when the user asks to design vertex labels, edge labels, properties, primary keys, indexes, or preview schema operations.
---

# HugeGraph Schema Designer

## Tool Routes

| Goal | Tool |
| --- | --- |
| Inspect current schema | `inspect_graph_tool(include_raw_schema=true)` |
| Design schema operations | `design_schema_tool(operations?)` |
| Validate schema operations | `apply_schema_tool(mode="validate", operations)` |
| Dry-run schema operations | `apply_schema_tool(mode="dry_run", operations)` |
| Execute real schema apply | No V1 stable tool |
| Delete or roll back schema | No V1 stable tool |

## Order

```text
inspect_graph_tool -> design_schema_tool
-> apply_schema_tool(mode="validate")
-> apply_schema_tool(mode="dry_run")
```
