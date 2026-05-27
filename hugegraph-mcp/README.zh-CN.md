# HugeGraph MCP

[English](README.md)

HugeGraph MCP 是一个基于 FastMCP 的 Model Context Protocol Server，将 HugeGraph 的常用操作收敛成 V1 稳定工具，让 AI 助手可以查看图状态、生成并执行只读 Gremlin、抽取候选图数据、设计和预览 schema 变更。

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
| `HUGEGRAPH_MCP_READONLY` | `true` | 阻止所有写操作 |
| `HUGEGRAPH_MCP_ALLOW_AI` | `false` | 允许调用 HugeGraph-AI |
| `HUGEGRAPH_MCP_ADMIN_MODE` | `false` | 启用 V1 默认关闭的管理/调试工具 |
| `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL` | `false` | 启用实验性 GraphRAG 问图调试路径 |
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

V1 安全默认值是 `readonly=true`、`allow_ai=false`、`sql_enabled=false`。如需启用 AI，设置 `HUGEGRAPH_MCP_ALLOW_AI=true`；如需启用写入，设置 `HUGEGRAPH_MCP_READONLY=false`；如需启用管理/调试工具，设置 `HUGEGRAPH_MCP_ADMIN_MODE=true`。

## 推荐第一步

连接 MCP 后，建议先调用 `inspect_graph_tool` 了解图状态，再按需调用其他工具：

```
inspect_graph_tool                     ← 了解图状态、schema 摘要、点边计数
    ↓
generate_gremlin_tool / execute_gremlin_read_tool
                                      ← 生成或执行只读 Gremlin
    ↓
design_schema_tool / apply_schema_tool
                                      ← 设计、校验或 dry-run schema
    ↓
extract_graph_data_tool               ← 从文本抽取候选图数据（不写入）
```

**写入安全链**：V1 中图数据 import 的确认写入必须走同一套流程：

```
dry_run=true → 审查 preview + 记录 plan_hash → dry_run=false + confirm=true + plan_hash
```

## 统一响应格式

V1 稳定工具返回统一 envelope，成功和失败都是同一结构：

成功响应 (`ok: true`)：

```json
{
  "ok": true,
  "data": { "vertex_count": 100, "edge_count": 250 },
  "error": null,
  "warnings": [],
  "next_actions": ["Use execute_gremlin_read_tool for read-only graph exploration"],
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

## V1 稳定工具

| 工具 | 说明 |
|------|------|
| `inspect_graph_tool` | 查看 HugeGraph Server 状态、schema 摘要、点边计数、readonly 状态和 AI 可用性 |
| `generate_gremlin_tool` | 自然语言生成 Gremlin；默认只生成，`execute=true` 且判定只读时才执行 |
| `execute_gremlin_read_tool` | 执行通过只读策略校验的 Gremlin traversal |
| `extract_graph_data_tool` | 从文本抽取候选 `{vertices, edges}`，不写入 HugeGraph |
| `import_graph_data_tool` | 通过 MCP 本地校验、dry-run/confirm 和 Gremlin 执行导入结构化图数据 |
| `delete_graph_data_tool` | 通过 MCP 本地校验、dry-run/confirm 和删除后反查，受控删除精确匹配的点或边 |
| `design_schema_tool` | 基于操作草案给出 schema 设计指导 |
| `apply_schema_tool` | 支持 `validate` 和 `dry_run`；V1 中 `apply` 返回 `FEATURE_DISABLED` |

旧的多 mode 兼容工具不再作为 V1 用户接口暴露；新接入直接使用上表中的稳定工具。

## 主要能力示例

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

### 2. 查询图

自然语言生成 Gremlin 使用 `generate_gremlin_tool`；已知 Gremlin 只读查询使用
`execute_gremlin_read_tool`。GraphRAG text 查询模式不作为 V1 用户接口暴露。

生成 Gremlin 并自动执行（仅限判定为只读时）：

```json
{
  "tool": "generate_gremlin_tool",
  "arguments": {
    "query": "按城市统计 person 顶点数量",
    "execute": true
  }
}
```

直接执行只读 Gremlin：

```json
{
  "tool": "execute_gremlin_read_tool",
  "arguments": {
    "gremlin_query": "g.V().hasLabel('person').limit(10).valueMap(true)"
  }
}
```

### 3. 设计和管理 Schema

Schema 设计使用 `design_schema_tool`；schema 校验和 dry-run 使用
`apply_schema_tool`。`apply` 保留为后续版本能力，当前返回 `FEATURE_DISABLED`。

获取分步 schema 设计引导：

```json
{
  "tool": "design_schema_tool",
  "arguments": { "operations": [] }
}
```

校验 schema 操作是否合法：

```json
{
  "tool": "apply_schema_tool",
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
  "tool": "apply_schema_tool",
  "arguments": {
    "mode": "dry_run",
    "operations": [
      { "type": "create_property_key", "name": "name", "data_type": "TEXT" },
      { "type": "create_vertex_label", "name": "person", "properties": ["name"], "primary_keys": ["name"] }
    ]
  }
}
```

V1 中如传入 `mode="apply"`，工具会返回 `FEATURE_DISABLED`。需要变更 schema 时，先使用 `dry_run` 审查 schema diff 和风险提示。

### 4. 图数据抽取、导入与受控删除

V1 保留两个公开结构化写入口：`import_graph_data_tool(mode="ingest")`
用于创建数据，`delete_graph_data_tool` 用于受控删除数据。
自然语言抽取候选图数据使用 `extract_graph_data_tool`。

结构化写入由 MCP 本地执行：`graph_data -> change_plan -> Gremlin`。写入前必须经过 schema 校验、`dry_run`、目标绑定 `plan_hash` 和 `confirm=true`。HugeGraph-AI 的 `/graph-import` 不作为公开写入路径使用。

`table`、`sql_preview`、`sql_mapping_suggest`、`sql_import`、`update` 和不受控删除模式在 V1 中禁用。

#### 从自然语言抽取图数据（不写入）

```json
{
  "tool": "extract_graph_data_tool",
  "arguments": {
    "text": "Alice 在 Acme 工作。Bob 认识 Alice。"
  }
}
```

#### 导入结构化图数据

先 dry-run：

```json
{
  "tool": "import_graph_data_tool",
  "arguments": {
    "mode": "ingest",
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
  "tool": "import_graph_data_tool",
  "arguments": {
    "mode": "ingest",
    "dry_run": false,
    "confirm": true,
    "plan_hash": "abc123fromDryRun",
    "graph_data": { ... }
  }
}
```

#### 受控删除图数据

`delete_graph_data_tool` 不接受用户传入 Gremlin，只接受结构化 `change_plan`。
第一版只支持精确删除 `delete_vertex` 和 `delete_edge`，每个操作必须唯一匹配一个对象。
不支持条件批量删除，也不支持级联删除；如果顶点有关联边，需要先显式删除边，再删除点。

删除点 dry-run：

```json
{
  "tool": "delete_graph_data_tool",
  "arguments": {
    "dry_run": true,
    "change_plan": {
      "operations": [
        {
          "op": "delete_vertex",
          "label": "person",
          "match": { "name": "Alice" },
          "cascade": false
        }
      ]
    }
  }
}
```

删除边 dry-run：

```json
{
  "tool": "delete_graph_data_tool",
  "arguments": {
    "dry_run": true,
    "change_plan": {
      "operations": [
        {
          "op": "delete_edge",
          "label": "knows",
          "source_label": "person",
          "source_match": { "name": "Alice" },
          "target_label": "person",
          "target_match": { "name": "Bob" }
        }
      ]
    }
  }
}
```

审查 dry-run 结果中的 `preview`、`matched_count`、`associated_edge_count`
和 `warnings`。确认无误后，传回 `plan_hash`、`nonce`、`expires_at` 执行：

```json
{
  "tool": "delete_graph_data_tool",
  "arguments": {
    "dry_run": false,
    "confirm": true,
    "plan_hash": "abc123fromDryRun",
    "nonce": "nonceFromDryRun",
    "expires_at": 1790000000,
    "change_plan": { "operations": [ ... ] }
  }
}
```

表格、SQL 和 update 工作流后移到后续版本。V1 中使用 `extract_graph_data_tool`
抽取候选数据，使用 `import_graph_data_tool(mode="ingest")` 创建结构化数据，
使用 `delete_graph_data_tool` 做受控删除。

## 安全模型

### 权限开关

| 开关 | `false` | `true`（默认值如上表所示） |
|------|-----------------|--------|
| `HUGEGRAPH_MCP_READONLY` | 所有能力可用 | 阻止 `DATA_WRITE`、`SCHEMA_WRITE`、`INDEX_WRITE`、`DEBUG_WRITE` |
| `HUGEGRAPH_MCP_ALLOW_AI` | AI 调用返回 `HUGEGRAPH_AI_UNAVAILABLE` | 允许 NL→Gremlin、图数据抽取 |
| `HUGEGRAPH_MCP_ADMIN_MODE` | 管理/调试工具返回 `FEATURE_DISABLED` | 允许直接写调试和刷新 embeddings |
| `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL` | GraphRAG text 用户接口不暴露 | 预留实验性 GraphRAG 调试配置 |

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
| `execute_gremlin_read_tool` | 允许（仅限判定为只读的 traversal） |
| `generate_gremlin_tool` | 需 `ALLOW_AI=true`；`execute=true` 时仍只能执行只读 traversal |
| `extract_graph_data_tool` | 需 `ALLOW_AI=true`；不写入 |
| `design_schema_tool` | 允许 |
| `apply_schema_tool`（validate/dry_run） | 允许 |
| `apply_schema_tool`（apply） | V1 禁用 |
| `import_graph_data_tool`（ingest dry_run） | 允许 |
| `import_graph_data_tool`（ingest confirm） | readonly=true 时拒绝 |
| `delete_graph_data_tool`（dry_run） | 允许 |
| `delete_graph_data_tool`（confirm） | readonly=true 时拒绝 |
| `refresh_vid_embeddings_tool` | 拒绝（需 confirm=true） |
| `execute_gremlin_write_tool` | 拒绝 |

### V1 默认禁用能力

以下能力在 V1 中默认禁用，调用时返回 `FEATURE_DISABLED`：

- SQL 和 SQL 导入路径：`sql_preview`、`sql_mapping_suggest`、`sql_import`
- 表格导入
- 图数据 update 和不受控 delete
- 直接 debug write（除非 `HUGEGRAPH_MCP_ADMIN_MODE=true`）
- 刷新 VID embeddings（除非 `HUGEGRAPH_MCP_ADMIN_MODE=true`）
- `apply_schema_tool` 的完整 schema apply

## 高级调试工具

以下工具用于维护和调试，普通流程建议优先使用 V1 稳定工具。

### `execute_gremlin_write_tool`

直接执行 Gremlin 写查询。常规数据写入应优先使用 `import_graph_data_tool(mode="ingest")`。

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
| `hugegraph-query-analyst` | 查询图数据；NL 生成 Gremlin 并只读执行 | `generate_gremlin_tool`、`execute_gremlin_read_tool` |
| `hugegraph-schema-designer` | 设计、校验和 dry-run schema 变更；完整 apply 属于后续版本能力 | `design_schema_tool`、`apply_schema_tool` |
| `hugegraph-data-importer` | 从自然语言抽取候选图数据，并通过结构化 graph_data 导入图数据或受控删除图数据；表格、SQL、update 属于后续版本能力 | `extract_graph_data_tool`、`import_graph_data_tool`、`delete_graph_data_tool` |
| `hugegraph-regression-tester` | 对用户能力做真实回归测试，包括写入、验证、清理和权限行为检查 | 上述工具组合 |

Skills 的定位是"怎么调用 MCP"的操作指南，不是绕过 MCP 的实现入口。例如导入或删除数据时，Skill 会要求先 dry-run、记录 `plan_hash`、再 confirm 写入、最后查询验证和清理；真正的创建仍通过 `import_graph_data_tool(mode="ingest")` 完成，真正的删除仍通过 `delete_graph_data_tool` 完成。

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
