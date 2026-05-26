# HugeGraph MCP

[English](README.md)

HugeGraph MCP 是一个基于 FastMCP 的 Model Context Protocol Server，将 HugeGraph 的常用操作收敛成 4 个高层 MCP 工具，让 AI 助手可以查看图状态、查询图数据、管理 schema、导入和管理图数据。

## 快速开始

### 前置条件

- HugeGraph Server（1.7.0+），例如 `http://127.0.0.1:8080`
- Python 3.10+
- `PATH` 中可用的 Git

### MCP 配置

在 IDE 或 AI 助手的 MCP 配置文件中加入：

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
        "HUGEGRAPH_MCP_READONLY": "true",
        "HUGEGRAPH_MCP_ALLOW_AI": "true"
      }
    }
  }
}
```

修改配置后重启 IDE 或 AI 助手即可生效。

如果首次安装依赖较慢，可以先本地预安装：

```bash
uvx --from git+https://github.com/hugegraph/hugegraph-ai.git@graph-mcp#subdirectory=hugegraph-mcp hugegraph-mcp
```

### 环境变量

所有变量均可选，有合理默认值：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HUGEGRAPH_URL` | `http://127.0.0.1:8080` | HugeGraph Server 地址 |
| `HUGEGRAPH_GRAPH_PATH` | `DEFAULT/hugegraph` | 格式 `GRAPH_SPACE/GRAPH_NAME` |
| `HUGEGRAPH_USER` | `admin` | 用户名 |
| `HUGEGRAPH_PASSWORD` | `""` | 密码 |
| `HUGEGRAPH_MCP_READONLY` | `false` | 阻止所有写操作 |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | 允许调用 HugeGraph-AI |
| `HUGEGRAPH_AI_URL` | `http://127.0.0.1:8001` | HugeGraph-AI 地址 |
| `HUGEGRAPH_AI_GRAPH_URL` | 未设置 | AI 端使用的图地址（默认同 `HUGEGRAPH_URL`） |
| `HUGEGRAPH_MCP_TIMEOUT_SECONDS` | `30` | AI 调用超时秒数 |
| `HUGEGRAPH_MCP_MAX_CONTEXT_ITEMS` | `100` | GraphRAG 最大上下文数 |
| `HUGEGRAPH_MCP_SQL_ENABLED` | `false` | 启用 SQLite 数据源 |
| `HUGEGRAPH_MCP_SQLITE_ALLOWLIST` | 空 | SQLite 文件路径 allowlist（分号分隔） |
| `HUGEGRAPH_MCP_SQL_MAX_PREVIEW_ROWS` | `20` | SQL 预览最大行数 |
| `HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS` | `1000` | SQL 导入最大行数 |
| `HUGEGRAPH_MCP_SQL_TIMEOUT_SECONDS` | `10` | SQLite 连接超时秒数 |

`READONLY` 和 `ALLOW_AI` 是两个独立开关：

- `READONLY=true` + `ALLOW_AI=true`：AI 辅助的读、查、抽取可用，但所有图写入被阻止（推荐给只读助手）。
- `READONLY=false` + `ALLOW_AI=true`：全功能可用。
- `READONLY=true` + `ALLOW_AI=false`：仅 Gremlin 直读可用。

## 推荐第一步

连接 MCP 后，建议先调用 `inspect_graph_tool` 了解图状态，再按需调用其他工具：

```
inspect_graph_tool                     ← 了解图状态、schema 摘要、点边计数
    ↓
query_graph_tool (mode="gremlin")     ← 探索图数据
    ↓
manage_schema_tool (mode="design")    ← 设计 schema（如需新增 label）
    ↓
manage_graph_data_tool                ← 导入或管理图数据
```

**写入安全链**：所有会修改图数据的操作（schema apply、数据 import/update/delete）都必须走同一套流程：

```
dry_run=true → 审查 preview + 记录 plan_hash → dry_run=false + confirm=true + plan_hash
```

## 统一响应格式

所有工具返回统一 envelope，成功和失败都是同一结构：

成功响应 (`ok: true`)：

```json
{
  "ok": true,
  "data": { "vertex_count": 100, "edge_count": 250 },
  "error": null,
  "warnings": [],
  "next_actions": ["Use query_graph_tool with mode='gremlin' for read-only graph exploration"],
  "meta": {
    "request_id": "req-a1b2c3d4e5f6",
    "graph": "hugegraph",
    "graphspace": "DEFAULT",
    "readonly": true,
    "duration_ms": 45.2
  }
}
```

错误响应 (`ok: false`)：

```json
{
  "ok": false,
  "data": null,
  "error": {
    "type": "READONLY_VIOLATION",
    "message": "DATA_WRITE capability is disabled in read-only mode",
    "suggestion": "Disable HUGEGRAPH_MCP_READONLY to allow this operation.",
    "retryable": false,
    "source": "hugegraph-mcp",
    "details": { "capability": "DATA_WRITE" }
  },
  "warnings": [],
  "next_actions": [],
  "meta": { "request_id": "req-b2c3d4e5f6a1", "graph": "hugegraph", "graphspace": "DEFAULT", "readonly": true, "duration_ms": 1.3 }
}
```

`data` 为 `null` 且 `error` 不为 `null` 表示失败；`warnings` 是非阻塞提示；`next_actions` 指引下一步操作。

## 四大能力

### 1. 查看图状态和 Schema — `inspect_graph_tool`

检视 HugeGraph Server 连接状态、schema 摘要、点边计数、索引状况、HugeGraph-AI 可用性。该工具是 best-effort 的：部分后端不可用时不会整体失败，而是在 `warnings` 中说明。

基础检查：

```json
{
  "tool": "inspect_graph_tool",
  "arguments": { "include_raw_schema": false }
}
```

需要完整 schema 用于排查或规划时：

```json
{
  "tool": "inspect_graph_tool",
  "arguments": { "include_raw_schema": true }
}
```

### 2. 查询图 — `query_graph_tool`

三种模式：

| mode | 功能 | 备注 |
|------|------|------|
| `text` | 自然语言问图（GraphRAG） | 需 `ALLOW_AI=true` |
| `generate` | NL → Gremlin 生成 | 默认不执行，`execute=true` 且判定只读时才执行 |
| `gremlin` | 直接执行只读 Gremlin | 不安全的 traversal 会被拒绝 |

自然语言问图：

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "text",
    "query": "Alice 认识哪些人？",
    "rag_mode": "graph_only",
    "include_evidence": true
  }
}
```

生成 Gremlin 并自动执行（仅限判定为只读时）：

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "generate",
    "query": "按城市统计 person 顶点数量",
    "execute": true
  }
}
```

直接执行只读 Gremlin：

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "gremlin",
    "gremlin_query": "g.V().hasLabel('person').limit(10).valueMap(true)"
  }
}
```

### 3. 设计和管理 Schema — `manage_schema_tool`

四种模式：`design` → `validate` → `dry_run` → `apply`。apply 必须走安全链。

获取分步 schema 设计引导：

```json
{
  "tool": "manage_schema_tool",
  "arguments": { "mode": "design" }
}
```

校验 schema 操作是否合法：

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "validate",
    "operations": [
      { "type": "create_property_key", "name": "name", "data_type": "TEXT" },
      { "type": "create_vertex_label", "name": "person", "properties": ["name"], "primary_keys": ["name"] }
    ]
  }
}
```

dry-run 生成 plan_hash（记下返回值中的 `plan_hash`）：

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "dry_run",
    "operations": [
      { "type": "create_property_key", "name": "name", "data_type": "TEXT" },
      { "type": "create_vertex_label", "name": "person", "properties": ["name"], "primary_keys": ["name"] }
    ]
  }
}
```

确认执行（`plan_hash` 必须来自同一次 dry-run）：

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "apply",
    "confirm": true,
    "plan_hash": "abc123fromDryRun",
    "operations": [
      { "type": "create_property_key", "name": "name", "data_type": "TEXT" },
      { "type": "create_vertex_label", "name": "person", "properties": ["name"], "primary_keys": ["name"] }
    ]
  }
}
```

### 4. 管理图数据 — `manage_graph_data_tool`

8 种 mode，覆盖完整的图数据生命周期：

| mode | 功能 | 写入？ |
|------|------|--------|
| `extract` | 自然语言 → 候选图数据 | 否 |
| `import` | 结构化图数据导入 | 是 |
| `table` | 表格行 → 图数据映射导入 | 是 |
| `sql_preview` | 预览 SQLite 表或 SELECT 结果 | 否 |
| `sql_mapping_suggest` | 生成 SQL 列到图 schema 的映射建议 | 否 |
| `sql_import` | SQL 查询结果 → 图数据导入 | 是 |
| `update` | 更新图元素 | 是 |
| `delete` | 删除图元素 | 是 |

#### 从自然语言抽取图数据（不写入）

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "extract",
    "text": "Alice 在 Acme 工作。Bob 认识 Alice。"
  }
}
```

#### 导入结构化图数据

先 dry-run：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "import",
    "dry_run": true,
    "graph_data": {
      "vertices": [
        { "label": "person", "id": "alice", "properties": { "name": "Alice" } },
        { "label": "person", "id": "bob", "properties": { "name": "Bob" } }
      ],
      "edges": [
        {
          "label": "knows",
          "source_label": "person", "target_label": "person",
          "source": { "name": "Bob" }, "target": { "name": "Alice" },
          "properties": {}
        }
      ]
    }
  }
}
```

审查 dry-run 结果中的 `preview`、`mutation_summary` 和 `warnings`。确认无误后，传回 `plan_hash` 执行：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "import",
    "dry_run": false,
    "confirm": true,
    "plan_hash": "abc123fromDryRun",
    "graph_data": { ... }
  }
}
```

#### 表格数据映射导入

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "table",
    "dry_run": true,
    "table_data": {
      "table_name": "employment",
      "columns": ["person_name", "company_name"],
      "rows": [["Alice", "Acme"], ["Bob", "Acme"]]
    },
    "mapping": {
      "vertex_mappings": [
        { "target_label": "person", "column_mapping": { "name": "person_name" }, "primary_key_columns": ["person_name"] },
        { "target_label": "company", "column_mapping": { "name": "company_name" }, "primary_key_columns": ["company_name"] }
      ],
      "edge_mappings": [
        {
          "target_label": "works_at",
          "source_vertex": { "label": "person", "primary_key_columns": ["person_name"] },
          "target_vertex": { "label": "company", "primary_key_columns": ["company_name"] },
          "column_mapping": {}
        }
      ]
    }
  }
}
```

#### 更新图元素

dry-run：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "update",
    "dry_run": true,
    "change_plan": {
      "operations": [
        { "op": "update_vertex", "label": "person", "match": { "name": "Alice" }, "set": { "age": 31 } }
      ]
    }
  }
}
```

确认执行：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "update",
    "dry_run": false,
    "confirm": true,
    "plan_hash": "def456fromDryRun",
    "change_plan": {
      "operations": [
        { "op": "update_vertex", "label": "person", "match": { "name": "Alice" }, "set": { "age": 31 } }
      ]
    }
  }
}
```

#### 删除图元素

dry-run（`cascade: false` 时，有关联边的顶点会被拒绝）：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "delete",
    "dry_run": true,
    "change_plan": {
      "operations": [
        { "op": "delete_vertex", "label": "person", "match": { "name": "Alice" }, "cascade": false }
      ]
    }
  }
}
```

确认执行：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "delete",
    "dry_run": false,
    "confirm": true,
    "plan_hash": "ghi789fromDryRun",
    "change_plan": {
      "operations": [
        { "op": "delete_vertex", "label": "person", "match": { "name": "Alice" }, "cascade": false }
      ]
    }
  }
}
```

## 从 SQL 导入图数据

SQL 导入是表格导入的上游能力：SQLite SELECT → `table_data` → mapping → `graph_data` → 安全链写入。当前只支持本地 SQLite。

启用 SQL 能力需配置环境变量：

```json
{
  "env": {
    "HUGEGRAPH_MCP_SQL_ENABLED": "true",
    "HUGEGRAPH_MCP_SQLITE_ALLOWLIST": "D:/data/hugegraph-import.sqlite3;D:/data/other.sqlite3"
  }
}
```

`sql_source` 格式：

```json
{ "type": "sqlite", "path": "D:/data/hugegraph-import.sqlite3" }
```

SQL 只允许只读语句（`SELECT`、`WITH ... SELECT`、`EXPLAIN`、信息类 `PRAGMA`）；`INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`CREATE` 等会被拒绝。

推荐三步流程：

**Step 1 — 预览数据** (`sql_preview`)：确认 SQL 结果列和行内容正确。

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_preview",
    "sql_source": { "type": "sqlite", "path": "D:/data/hugegraph-import.sqlite3" },
    "sql_query": "SELECT source_name, target_name, work_date FROM employee_relations"
  }
}
```

**Step 2 — 生成映射建议** (`sql_mapping_suggest`)：基于列名和 live schema 自动生成可编辑的 mapping 草稿。

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_mapping_suggest",
    "sql_source": { "type": "sqlite", "path": "D:/data/hugegraph-import.sqlite3" },
    "sql_query": "SELECT source_name, target_name, work_date FROM employee_relations"
  }
}
```

检查返回的 `mapping_suggestion`，确认 `target_label`、`column_mapping`、`primary_key_columns` 是否与 live schema 一致，必要时手动修改。

**Step 3 — 导入** (`sql_import`)：先 dry-run，审查 `plan_hash` 后确认执行。

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_import",
    "dry_run": true,
    "sql_source": { "type": "sqlite", "path": "D:/data/hugegraph-import.sqlite3" },
    "sql_query": "SELECT source_name, target_name, work_date FROM employee_relations",
    "mapping": {
      "vertex_mappings": [
        { "target_label": "person", "column_mapping": { "name": "source_name" }, "primary_key_columns": ["source_name"] },
        { "target_label": "person", "column_mapping": { "name": "target_name" }, "primary_key_columns": ["target_name"] }
      ],
      "edge_mappings": [
        {
          "target_label": "colleague",
          "source_vertex": { "label": "person", "primary_key_columns": ["source_name"] },
          "target_vertex": { "label": "person", "primary_key_columns": ["target_name"] },
          "column_mapping": { "date": "work_date" }
        }
      ]
    }
  }
}
```

SQL 导入的 `plan_hash` 绑定 SQL source、SQL query、mapping 和图变更计划；确认执行时必须传 dry-run 返回的同一个 `plan_hash`。

## 兼容入口

`import_graph_data_tool` 保留用于兼容旧流程，支持 `extract` / `ingest` / `table` 三种 mode。新流程推荐使用 `manage_graph_data_tool`。

## 安全模型

### 权限开关

| 开关 | `false`（默认） | `true` |
|------|-----------------|--------|
| `HUGEGRAPH_MCP_READONLY` | 所有能力可用 | 阻止 `DATA_WRITE`、`SCHEMA_WRITE`、`INDEX_WRITE`、`DEBUG_WRITE` |
| `HUGEGRAPH_MCP_ALLOW_AI` | AI 调用返回 `HUGEGRAPH_AI_UNAVAILABLE` | 允许 NL→Gremlin、GraphRAG、图数据抽取 |

### 写入安全链

所有会修改图的操作都必须走：**dry_run → 审查 preview → plan_hash 匹配 → confirm=true**。

这确保了：
- 操作执行前已被预览和确认
- `plan_hash` 防止 dry-run 和执行之间 schema/数据被篡改
- `readonly=true` 时所有写入在 guard 层被阻止（不依赖工具内逻辑）

### 各工具在 readonly 模式下的行为

| 工具 | readonly=true 行为 |
|------|---------------------|
| `inspect_graph_tool` | 始终允许 |
| `query_graph_tool`（gremlin） | 允许（仅限判定为只读的 traversal） |
| `query_graph_tool`（text/generate） | 需 `ALLOW_AI=true` |
| `manage_schema_tool`（design/validate/dry_run） | 允许 |
| `manage_schema_tool`（apply） | 拒绝 |
| `manage_graph_data_tool`（extract/table/sql_preview/sql_mapping_suggest/dry_run） | 允许 |
| `manage_graph_data_tool`（import/sql_import/update/delete confirm） | 拒绝 |
| `refresh_vid_embeddings_tool` | 拒绝（需 confirm=true） |
| `execute_gremlin_write_tool` | 拒绝 |

## 高级调试工具

以下工具用于维护和调试，普通流程建议优先使用四大能力。

### `execute_gremlin_write_tool`

直接执行 Gremlin 写查询。常规数据写入应优先使用 `manage_graph_data_tool`。

```json
{
  "tool": "execute_gremlin_write_tool",
  "arguments": { "gremlin_query": "g.addV('person').property('name', 'Alice')" }
}
```

### `refresh_vid_embeddings_tool`

通过 HugeGraph-AI 刷新 VID embeddings，需要显式确认。

```json
{
  "tool": "refresh_vid_embeddings_tool",
  "arguments": { "confirm": true }
}
```

## 配套 Skills

Skills 是 agent 侧的工作流说明，帮助 AI 助手选择正确的 MCP 能力、组织 dry-run/confirm/验证/清理流程并规范输出。它们不是 MCP 协议的一部分，也不是权限边界——实际权限仍由 MCP server 的 guard 执行。

如果客户端支持 Skills，可配置以下 5 个 Skill：

| Skill | 适用场景 | 主要 MCP 路径 |
| --- | --- | --- |
| `hugegraph-operator` | 查看图状态、schema、服务健康、权限、AI 可用性、计数和索引 | `inspect_graph_tool` |
| `hugegraph-query-analyst` | 查询图数据；NL 生成 Gremlin 并只读执行；需要证据召回时使用 GraphRAG | `query_graph_tool` |
| `hugegraph-schema-designer` | 设计、校验、dry-run 和安全 apply schema 变更 | `manage_schema_tool` |
| `hugegraph-data-importer` | 从自然语言、结构化图数据、表格行或 SQL 结果导入图数据；更新和删除图数据 | `manage_graph_data_tool` |
| `hugegraph-regression-tester` | 对用户能力做真实回归测试，包括写入、验证、清理和权限行为检查 | 上述工具组合 |

Skills 的定位是"怎么调用 MCP"的操作指南，不是绕过 MCP 的实现入口。例如导入数据时，Skill 会要求先 dry-run、记录 `plan_hash`、再 confirm 写入、最后查询验证和清理；真正的写入仍通过 `manage_graph_data_tool` 完成。

支持 Skills 的客户端通常从本地目录加载：

```text
$CODEX_HOME/skills/
  hugegraph-operator/
  hugegraph-query-analyst/
  hugegraph-schema-designer/
  hugegraph-data-importer/
  hugegraph-regression-tester/
```

## License

Apache License 2.0
