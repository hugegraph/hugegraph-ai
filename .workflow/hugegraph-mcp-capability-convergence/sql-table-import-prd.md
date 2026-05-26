# PRD: HugeGraph MCP SQL 表导入图数据能力

日期：2026-05-26

关联需求：[requirements.md](./requirements.md)

## 1. 介绍

当前 HugeGraph MCP 已经将用户主能力收敛为查看图状态和 schema、查询图、设计和管理 schema、管理图数据。管理图数据能力已经支持自然语言抽取、结构化 `graph_data`、表格 `table_data + mapping`，并复用统一的 live schema 校验、dry-run、`plan_hash`、`confirm` 和 readonly guard。

但是，当前“结构化 SQL 表导入图数据”仍停留在“用户手动传入 table_data”的层面。用户如果有本地 SQLite 表或 SQL 查询结果，需要先自己把 SQL 数据导出为 rows，再手动组装成 `table_data`。这会降低数据集成效率，也容易出现字段错位、主键遗漏、mapping 不清晰等问题。

本 PRD 定义 SQL 表导入图数据能力的第一阶段实现。系统应优先支持本地 SQLite 数据源，并将 SQL 查询结果转换为现有 `table_data`，再复用当前 `manage_graph_data_tool` 的表格映射和图数据写入安全链路。该能力不新增一套独立写图机制，不绕过现有 schema 校验、dry-run、`plan_hash`、`confirm` 和 readonly 控制。

本地已发现可用于验收的 SQLite 数据源：

```text
D:\Code\agent_learning\agent_rag\agent\retrieval.sqlite3
```

该库包含 `chunks`、`idf`、`bm25_idf` 表，可作为 SQL preview、mapping 建议和 SQL import 的真实样例数据源。

## 2. 目标

### 2.1 产品目标

- 支持用户从本地 SQLite 数据库读取表结构、样例行和 SELECT 查询结果。
- 支持将 SQL 查询结果转换为现有 `table_data` 格式。
- 支持根据 SQL columns 和 HugeGraph live schema 生成可编辑 mapping 建议。
- 支持将 SQL 查询结果通过现有 `table_data -> graph_data -> change_plan -> dry-run -> confirm` 链路导入 HugeGraph。
- 所有 SQL 导入写入路径复用现有图数据管理能力的权限、安全和返回结构。
- 第一阶段尽可能复用现有功能，避免引入新的普通用户主入口。

### 2.2 非目标

- 不在第一阶段支持 MySQL、PostgreSQL、SQL Server、Oracle 等外部数据库直连。
- 不在第一阶段支持数据库账号、密码、连接池或远程网络数据库管理。
- 不支持执行 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`ATTACH`、`DETACH`、`PRAGMA` 等非只读 SQL。
- 不实现自然语言自动理解 SQL 表并自动生成完整导入方案。
- 不自动创建 HugeGraph schema。
- 不绕过现有 `manage_graph_data_tool` 的 dry-run、`plan_hash`、`confirm` 和 readonly guard。
- 不实现大规模 ETL、断点续传、失败回滚或完整审计系统。

## 3. 用户和场景

### 3.1 目标用户

- 希望把本地 SQLite 数据转换为 HugeGraph 图数据的 Agent 用户。
- 维护知识图谱导入流程的开发者。
- 需要从结构化表或 SQL 查询结果构造点边的测试者。
- 需要在写入前预览 SQL 数据、mapping 和图写入影响的管理员。

### 3.2 典型场景

- 用户查看 SQLite 数据库中有哪些表和字段。
- 用户预览 `chunks` 表的前 10 行，确认字段含义。
- 用户执行只读 SELECT 查询，生成 `table_data`。
- 用户把 SQL 查询结果映射为 `webpage` 顶点。
- 用户在 dry-run 中查看将创建多少顶点和边。
- 用户确认 `plan_hash` 后执行真实导入。
- 用户在 readonly 模式下只允许 preview 和 dry-run，不允许真实写入。

## 4. 入口设计

本能力应作为 `manage_graph_data_tool` 的扩展 mode，而不是新增普通用户主工具。

新增 mode：

```text
sql_preview
sql_mapping_suggest
sql_import
```

建议参数：

```text
mode: "sql_preview" | "sql_mapping_suggest" | "sql_import"
sql_source: dict | null
sql_query: str | null
table_name: str | null
mapping: dict | null
target: dict | null
dry_run: bool = true
confirm: bool = false
plan_hash: str | null
```

`sql_source` 第一阶段仅支持 SQLite：

```json
{
  "type": "sqlite",
  "path": "D:\\Code\\agent_learning\\agent_rag\\agent\\retrieval.sqlite3"
}
```

## 5. 需求列表

### 5.1 SQL 数据源配置

- **用户故事**: 作为一名 **系统管理员**, 我希望 **显式控制哪些 SQLite 文件可以被 MCP 读取**, 以便 **避免 Agent 任意读取本地数据库文件**。
- **验收标准 (EARS 格式)**:
  - **SQL-U1**: The **HugeGraph MCP** shall **默认关闭 SQL 数据源能力，除非 `HUGEGRAPH_MCP_SQL_ENABLED=true`**。
  - **SQL-U2**: The **HugeGraph MCP** shall **通过 allowlist 限制可访问的 SQLite 文件路径**。
  - **SQL-U3**: The **HugeGraph MCP** shall **拒绝访问不在 allowlist 中的 SQLite 文件**。
  - **SQL-U4**: The **HugeGraph MCP** shall **在错误输出中说明 SQL 能力未启用或数据源未授权的具体原因**。
  - **SQL-X1**: IF **`sql_source.type` 不是 `sqlite`**, THEN the **HugeGraph MCP** shall **返回 `UNSUPPORTED_SQL_SOURCE` 或等价错误，并说明第一阶段仅支持 SQLite**。

建议环境变量：

```text
HUGEGRAPH_MCP_SQL_ENABLED=false
HUGEGRAPH_MCP_SQLITE_ALLOWLIST=D:\Code\agent_learning\agent_rag\agent\retrieval.sqlite3
HUGEGRAPH_MCP_SQL_MAX_PREVIEW_ROWS=20
HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS=1000
HUGEGRAPH_MCP_SQL_TIMEOUT_SECONDS=10
```

### 5.2 只读 SQL 安全

- **用户故事**: 作为一名 **系统管理员**, 我希望 **SQL 能力只能读取数据**, 以便 **防止 Agent 修改本地 SQLite 数据库**。
- **验收标准 (EARS 格式)**:
  - **SQL-S1**: WHILE **执行 SQL 查询**, the **HugeGraph MCP** shall **使用 SQLite 只读连接打开数据库**。
  - **SQL-S2**: WHILE **执行 SQL 查询**, the **HugeGraph MCP** shall **启用 SQLite `query_only` 或等价只读限制**。
  - **SQL-S3**: The **HugeGraph MCP** shall **使用 SQLite authorizer 或等价机制拒绝写入、DDL、attach、detach 和危险 pragma**。
  - **SQL-S4**: The **HugeGraph MCP** shall **只允许单条 `SELECT` 或 `WITH ... SELECT` 查询**。
  - **SQL-X2**: IF **SQL 包含多语句**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 `UNSAFE_SQL`**。
  - **SQL-X3**: IF **SQL 包含 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`CREATE`、`REPLACE`、`ATTACH`、`DETACH` 或危险 `PRAGMA`**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 `UNSAFE_SQL`**。
  - **SQL-X4**: IF **SQL 查询超时**, THEN the **HugeGraph MCP** shall **停止执行并返回可恢复错误**。

### 5.3 SQL Preview

- **用户故事**: 作为一名 **数据集成用户**, 我希望 **先查看 SQL 表结构和样例行**, 以便 **确认数据是否适合导入图数据库**。
- **验收标准 (EARS 格式)**:
  - **SQL-E1**: WHEN **用户请求 `mode="sql_preview"` 且提供 `table_name`**, the **HugeGraph MCP** shall **返回该表的 columns、类型信息、样例行和估算行数**。
  - **SQL-E2**: WHEN **用户请求 `mode="sql_preview"` 且提供 `sql_query`**, the **HugeGraph MCP** shall **执行只读 SELECT 并返回 columns、rows、row_count 和 truncated 状态**。
  - **SQL-E3**: WHEN **preview 查询未显式包含 LIMIT**, the **HugeGraph MCP** shall **自动限制返回行数不超过 `HUGEGRAPH_MCP_SQL_MAX_PREVIEW_ROWS`**。
  - **SQL-E4**: WHEN **preview 成功**, the **HugeGraph MCP** shall **以统一 envelope 返回结果，并包含 `source_ref`、`columns`、`rows`、`row_count`、`truncated`**。
  - **SQL-X5**: IF **目标表不存在**, THEN the **HugeGraph MCP** shall **返回结构化错误并列出可用表或建议用户先查看数据源 schema**。

### 5.4 SQL 查询结果转 table_data

- **用户故事**: 作为一名 **开发者**, 我希望 **SQL 查询结果自动转换成现有 `table_data`**, 以便 **复用当前表格导入图数据能力**。
- **验收标准 (EARS 格式)**:
  - **SQL-E5**: WHEN **只读 SQL 查询执行成功**, the **HugeGraph MCP** shall **将结果转换为 `table_data.columns` 和 `table_data.rows`**。
  - **SQL-E6**: WHEN **SQL 结果包含 SQLite 类型**, the **HugeGraph MCP** shall **保留可 JSON 序列化的值，并对 BLOB 或不可序列化值返回 warning 或可读摘要**。
  - **SQL-E7**: WHEN **SQL 结果列名重复或为空**, the **HugeGraph MCP** shall **生成稳定列名或拒绝导入，并在错误中指出问题列**。
  - **SQL-E8**: WHEN **SQL 查询结果为空**, the **HugeGraph MCP** shall **返回空 rows 和 warning，不应执行真实写入**。
  - **SQL-X6**: IF **SQL import 查询结果超过 `HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS` 且未启用分批导入**, THEN the **HugeGraph MCP** shall **拒绝导入或要求用户缩小查询范围**。

### 5.5 Mapping 建议

- **用户故事**: 作为一名 **Agent 用户**, 我希望 **系统根据 SQL columns 和 HugeGraph schema 生成 mapping 建议**, 以便 **减少手写 mapping 的成本，同时保留人工确认能力**。
- **验收标准 (EARS 格式)**:
  - **SQL-E9**: WHEN **用户请求 `mode="sql_mapping_suggest"`**, the **HugeGraph MCP** shall **基于 SQL columns、表名、样例行和 live schema 返回可编辑 mapping 建议**。
  - **SQL-E10**: WHEN **SQL column 与 HugeGraph property 同名**, the **HugeGraph MCP** shall **优先建议映射到该 property**。
  - **SQL-E11**: WHEN **用户指定目标 vertex label 或 edge label**, the **HugeGraph MCP** shall **优先围绕用户指定目标生成 mapping**。
  - **SQL-E12**: WHEN **无法可靠生成边 mapping**, the **HugeGraph MCP** shall **至少返回顶点 mapping 建议，并在 warnings 中说明需要用户补充 source/target 规则**。
  - **SQL-E13**: The **HugeGraph MCP** shall **复用现有 `import_table.suggest_table_mapping()`，并在此基础上增加 live schema 感知逻辑**。
  - **SQL-X7**: IF **live schema 无法读取**, THEN the **HugeGraph MCP** shall **返回连接错误或降级为基础 columns mapping 建议，并明确标注 schema 不可用**。

### 5.6 SQL Import

- **用户故事**: 作为一名 **数据集成用户**, 我希望 **把 SQL 查询结果按 mapping 导入 HugeGraph**, 以便 **将行列式数据转成图中的点和边**。
- **验收标准 (EARS 格式)**:
  - **SQL-E14**: WHEN **用户请求 `mode="sql_import"`**, the **HugeGraph MCP** shall **先执行只读 SQL，并将结果转换为 `table_data`**。
  - **SQL-E15**: WHEN **`table_data` 生成成功**, the **HugeGraph MCP** shall **调用现有表格导入逻辑生成 `graph_data`**。
  - **SQL-E16**: WHEN **`graph_data` 生成成功**, the **HugeGraph MCP** shall **复用现有 graph payload 校验、change_plan 转换和 dry-run 流程**。
  - **SQL-E17**: WHEN **`sql_import` dry-run 成功**, the **HugeGraph MCP** shall **返回 `plan_hash`、`mutation_summary`、`preview`、SQL 数据摘要和 mapping 摘要**。
  - **SQL-E18**: WHEN **用户确认执行 `sql_import`**, the **HugeGraph MCP** shall **要求 `dry_run=false`、`confirm=true` 和匹配的 `plan_hash`**。
  - **SQL-E19**: WHEN **`sql_import` 执行成功**, the **HugeGraph MCP** shall **返回写入摘要，并建议用户按需查询验证或刷新索引**。
  - **SQL-X8**: IF **mapping 缺失或不完整**, THEN the **HugeGraph MCP** shall **不写入图数据库，并返回 mapping 建议或要求用户补充 mapping**。
  - **SQL-X9**: IF **SQL 查询结果映射出的 graph_data 不符合 live schema**, THEN the **HugeGraph MCP** shall **拒绝导入并返回 schema mismatch 详情**。
  - **SQL-X10**: IF **confirm 时 SQL 查询、mapping、目标图、schema 上下文或生成的 change_plan 与 dry-run 不一致**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 `PLAN_HASH_MISMATCH`**。

### 5.7 plan_hash 绑定

- **用户故事**: 作为一名 **测试者或管理员**, 我希望 **SQL 导入确认执行时绑定 dry-run 的确切计划**, 以便 **避免预览和真实写入使用不同数据或 mapping**。
- **验收标准 (EARS 格式)**:
  - **SQL-E20**: WHEN **`sql_import` dry-run 成功**, the **HugeGraph MCP** shall **生成与 SQL 导入计划绑定的 `plan_hash`**。
  - **SQL-E21**: The **HugeGraph MCP** shall **将 `sql_source`、规范化后的 `sql_query`、mapping、目标 graph、graphspace、live schema 摘要和生成的 change_plan 纳入 hash 输入**。
  - **SQL-E22**: WHEN **confirm 执行**, the **HugeGraph MCP** shall **重新读取 SQL、重新生成 table_data、graph_data 和 change_plan，并重新计算 `plan_hash`**。
  - **SQL-X11**: IF **SQL 数据在 dry-run 后发生变化并导致 change_plan 变化**, THEN the **HugeGraph MCP** shall **拒绝执行并要求重新 dry-run**。
  - **SQL-X12**: IF **实现无法基于计划内容重新计算 `plan_hash`**, THEN the **HugeGraph MCP** shall **不得允许 confirm 执行**。

### 5.8 readonly 和权限控制

- **用户故事**: 作为一名 **系统管理员**, 我希望 **readonly 模式下 SQL 可以读取但不能写入图**, 以便 **安全地在生产图上预览导入计划**。
- **验收标准 (EARS 格式)**:
  - **SQL-S5**: WHILE **`HUGEGRAPH_MCP_READONLY=true`**, the **HugeGraph MCP** shall **允许 `sql_preview` 和 `sql_import dry_run`**。
  - **SQL-S6**: WHILE **`HUGEGRAPH_MCP_READONLY=true`**, the **HugeGraph MCP** shall **拒绝 `sql_import` 的真实写入 apply 路径**。
  - **SQL-S7**: WHILE **SQL 能力未启用**, the **HugeGraph MCP** shall **拒绝所有 SQL source 访问，但不影响现有非 SQL 图数据管理能力**。
  - **SQL-S8**: The **HugeGraph MCP** shall **不要求 `HUGEGRAPH_MCP_ALLOW_AI=true` 才能执行确定性的 SQL preview 或 SQL import**。

### 5.9 输出结构和错误

- **用户故事**: 作为一名 **Agent 用户**, 我希望 **SQL 导入相关输出与其他主能力一致**, 以便 **Agent 可以稳定判断下一步动作**。
- **验收标准 (EARS 格式)**:
  - **SQL-U5**: The **HugeGraph MCP** shall **对 SQL preview、mapping suggest 和 import 返回统一 envelope**。
  - **SQL-U6**: The **HugeGraph MCP** shall **在 `meta` 中返回 `request_id`、graph、graphspace、readonly 和耗时信息**。
  - **SQL-E23**: WHEN **SQL 查询成功但结果被截断**, the **HugeGraph MCP** shall **在 warnings 中说明截断原因和最大行数限制**。
  - **SQL-E24**: WHEN **SQL 导入 dry-run 失败**, the **HugeGraph MCP** shall **返回具体失败阶段，例如 SQL validation、SQL execution、table mapping、graph schema validation 或 change_plan validation**。
  - **SQL-X13**: IF **SQLite 文件不可读或损坏**, THEN the **HugeGraph MCP** shall **返回连接或数据源错误，并建议检查路径、allowlist 和文件状态**。

## 6. 数据结构

### 6.1 sql_source

```json
{
  "type": "sqlite",
  "path": "D:\\Code\\agent_learning\\agent_rag\\agent\\retrieval.sqlite3"
}
```

### 6.2 sql_preview 输出

```json
{
  "ok": true,
  "data": {
    "source_ref": {
      "type": "sqlite",
      "path": "D:\\Code\\agent_learning\\agent_rag\\agent\\retrieval.sqlite3"
    },
    "columns": [
      {"name": "chunk_id", "type": "INTEGER"},
      {"name": "source_path", "type": "TEXT"},
      {"name": "section_title", "type": "TEXT"}
    ],
    "rows": [
      [0, "01-agentic-rag-survey.md", "Abstract"]
    ],
    "row_count": 1,
    "truncated": false
  },
  "error": null,
  "warnings": [],
  "next_actions": []
}
```

### 6.3 table_data 中间格式

```json
{
  "table_name": "chunks_preview",
  "columns": ["name", "url"],
  "rows": [
    ["01-agentic-rag-survey.md:Abstract", "01-agentic-rag-survey.md"]
  ]
}
```

### 6.4 mapping 示例

```json
{
  "vertex_mappings": [
    {
      "target_label": "webpage",
      "column_mapping": {
        "name": "name",
        "url": "url"
      },
      "primary_key_columns": ["name"]
    }
  ],
  "edge_mappings": []
}
```

### 6.5 sql_import 示例

```json
{
  "mode": "sql_import",
  "sql_source": {
    "type": "sqlite",
    "path": "D:\\Code\\agent_learning\\agent_rag\\agent\\retrieval.sqlite3"
  },
  "sql_query": "SELECT source_path || ':' || section_title AS name, source_path AS url FROM chunks WHERE section_title IS NOT NULL LIMIT 3",
  "mapping": {
    "vertex_mappings": [
      {
        "target_label": "webpage",
        "column_mapping": {
          "name": "name",
          "url": "url"
        },
        "primary_key_columns": ["name"]
      }
    ],
    "edge_mappings": []
  },
  "dry_run": true
}
```

## 7. 实施阶段

### Phase 1: SQL 适配层

新增模块：

```text
hugegraph_mcp/tools/sql_table.py
```

核心函数：

```text
validate_sqlite_source()
validate_readonly_sql()
preview_sql()
execute_select_to_table_data()
normalize_sql_query()
```

验收：

- 能读取 allowlist 中的 SQLite。
- 能拒绝非 allowlist SQLite。
- 能拒绝非只读 SQL。
- 能把 SELECT 结果转换为 `table_data`。

### Phase 2: MCP 入口接入

修改：

```text
hugegraph_mcp/server.py
hugegraph_mcp/tools/manage_graph_data.py
```

验收：

- `manage_graph_data_tool mode="sql_preview"` 可用。
- `manage_graph_data_tool mode="sql_mapping_suggest"` 可用。
- `manage_graph_data_tool mode="sql_import"` 可用。
- 不新增普通用户主工具。

### Phase 3: 复用图数据导入链路

复用：

```text
import_table_data()
graph_data_to_change_plan()
manage_graph_data(mode="import")
```

验收：

- `sql_import dry_run` 返回现有图数据 dry-run 结构。
- `sql_import apply` 复用现有 DATA_WRITE guard。
- `readonly=true` 时 apply 被拒绝。

### Phase 4: plan_hash 加强

修改：

```text
calculate_graph_change_plan_hash()
```

或新增 SQL import 专用 hash 计算函数，但必须复用同一确认语义。

验收：

- dry-run 和 confirm 输入一致时允许执行。
- SQL query 变化时拒绝。
- mapping 变化时拒绝。
- SQL 数据变化导致 change_plan 变化时拒绝。
- schema 摘要变化时拒绝。

### Phase 5: 文档和测试

新增或修改：

```text
tests/test_sql_table.py
tests/test_manage_graph_data_sql.py
README.md
README.zh-CN.md
```

验收：

- README 包含 SQLite SQL preview、mapping suggest、dry-run、confirm 示例。
- 中文 README 同步说明。
- 单元测试和现有回归测试通过。

## 8. 测试要求

### 8.1 单元测试

必须覆盖：

- SQL disabled 时拒绝。
- SQLite 文件不在 allowlist 时拒绝。
- SQLite 文件不存在时返回数据源错误。
- `SELECT` 成功。
- `WITH ... SELECT` 成功。
- 多语句 SQL 被拒绝。
- `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`ATTACH`、`DETACH` 被拒绝。
- preview 自动限制行数。
- 查询结果转 `table_data`。
- BLOB 或不可 JSON 序列化值处理。
- mapping suggest 输出稳定结构。
- `sql_import dry_run` 复用现有 import 校验。
- `sql_import apply` 缺少 confirm 时拒绝。
- `plan_hash` 不匹配时拒绝。
- `readonly=true` 时 apply 拒绝。

### 8.2 Live 验收测试

使用本地 SQLite：

```text
D:\Code\agent_learning\agent_rag\agent\retrieval.sqlite3
```

测试 SQL：

```sql
SELECT
  source_path || ':' || section_title AS name,
  source_path AS url
FROM chunks
WHERE section_title IS NOT NULL
LIMIT 3
```

验收流程：

```text
inspect_graph_tool
-> manage_graph_data_tool mode="sql_preview"
-> manage_graph_data_tool mode="sql_mapping_suggest"
-> manage_graph_data_tool mode="sql_import" dry_run=true
-> manage_graph_data_tool mode="sql_import" dry_run=false confirm=true plan_hash=...
-> query_graph_tool 查询导入的 webpage 顶点
-> manage_graph_data_tool mode="delete" 清理测试顶点
-> inspect_graph_tool 复查计数
```

### 8.3 回归测试

必须运行：

```powershell
cd D:\Code\agent_learning\hugegraph-ai\hugegraph-mcp
uv run pytest
```

如修改 README 示例，还应执行文档样例对应的 MCP live 验收。

## 9. 验收清单

- [ ] SQL 能力默认关闭。
- [ ] SQLite allowlist 生效。
- [ ] 只读 SQL 安全校验生效。
- [ ] `sql_preview` 能返回 columns、rows、row_count 和 truncated。
- [ ] SQL 查询结果能转换为 `table_data`。
- [ ] `sql_mapping_suggest` 能基于 live schema 返回可编辑 mapping。
- [ ] `sql_import dry_run` 复用现有图数据 dry-run 输出。
- [ ] `sql_import apply` 需要 `confirm=true` 和匹配 `plan_hash`。
- [ ] `readonly=true` 时 SQL preview/dry-run 允许，SQL import apply 拒绝。
- [ ] SQL query、mapping、schema 或生成的 change_plan 变化时 confirm 被拒绝。
- [ ] 现有自然语言抽图、结构化 graph_data 导入、table_data 导入、update/delete 不回归。
- [ ] README 和中文 README 更新。

## 10. 开放问题

- 第一阶段是否只允许本地绝对路径 SQLite，还是允许 workspace 相对路径。
- `HUGEGRAPH_MCP_SQLITE_ALLOWLIST` 是否支持多个路径，路径分隔符采用分号还是 JSON 数组。
- 对大表是否直接拒绝超过上限，还是在第一阶段支持分批读取。
- mapping suggest 是否需要调用 AI，还是第一阶段保持完全确定性。
- 是否需要在 inspect graph 输出中展示 SQL 能力状态。
