# HugeGraph MCP 改造前后功能对比

日期：2026-05-26

## 1. 文档目的

本文对比 HugeGraph MCP 在本轮改造前后的功能变化，说明已经改造的范围、当前用户可以使用的能力、底层安全机制变化，以及仍保留为兼容或调试用途的能力。

本对比基于以下本地材料和当前代码状态：

- [requirements.md](./requirements.md)
- [execution-plan.md](./execution-plan.md)
- [manage-graph-data-prd.md](./manage-graph-data-prd.md)
- [sql-table-import-prd.md](./sql-table-import-prd.md)
- `hugegraph-mcp/hugegraph_mcp/server.py`
- `hugegraph-mcp/README.md`
- `hugegraph-mcp/README.zh-CN.md`

## 2. 总体结论

改造前，HugeGraph MCP 更像是一组分散的底层工具集合：schema 查询、Gremlin 执行、自然语言问图、Gremlin 生成、schema 操作、文本抽图、图数据导入等能力分别暴露，用户需要理解多个入口的差异，也更容易误用底层写入工具。

改造后，MCP 已经收敛为以主功能为中心的工具面：

1. 查看图状态和 schema。
2. 查询图。
3. 设计和管理 schema。
4. 管理图数据，包括自然语言抽图、结构化 graph data、表格导入、SQL 表导入、更新和删除。

同时，改造补上了统一 envelope、readonly guard、AI 开关、dry-run、`plan_hash`、`confirm=true`、live schema 校验、SQL 只读限制等安全边界。

当前仍保留少量兼容和调试入口：

- `import_graph_data_tool`：兼容旧图数据导入入口。
- `refresh_vid_embeddings_tool`：高级索引维护能力。
- `execute_gremlin_write_tool`：高级调试/管理员直接写 Gremlin 能力。

## 3. 工具面变化

### 3.1 改造前

改造前用户面对的是较分散的底层能力。按执行计划描述，入口收敛目标来自“12 -> 6 tools”的问题背景。典型旧能力包括：

| 改造前能力 | 典型问题 |
| --- | --- |
| 单独查询 schema | 只能拿 schema，缺少图状态、计数、AI 状态、readonly 状态的统一视图 |
| 单独执行只读 Gremlin | 用户需要自己知道 Gremlin 是否安全、是否只读 |
| 单独自然语言问图 | 和 Gremlin 生成、只读执行割裂 |
| 单独生成 Gremlin | 默认执行语义不统一，和只读执行安全边界分散 |
| 单独设计 schema | 和 schema apply/dry-run 不够统一 |
| 单独执行 schema 操作 | 容易绕过统一校验和确认语义 |
| 单独文本抽图 | 抽取和导入分离，用户需要自己串联 |
| 单独图数据 ingest | 校验、安全链和兼容输出不统一 |
| 直接 Gremlin 写入 | 可完成更新/删除，但不适合作为普通用户主路径 |

### 3.2 改造后

当前代码中暴露的 MCP 工具为：

| 当前工具 | 定位 | 用户路径 |
| --- | --- | --- |
| `inspect_graph_tool` | 查看图状态和 schema | 主路径 |
| `query_graph_tool` | 查询图 | 主路径 |
| `manage_schema_tool` | 设计和管理 schema | 主路径 |
| `manage_graph_data_tool` | 管理图数据 | 主路径 |
| `import_graph_data_tool` | 旧导入兼容入口 | 兼容路径 |
| `refresh_vid_embeddings_tool` | VID embedding 刷新 | 高级维护 |
| `execute_gremlin_write_tool` | 直接 Gremlin 写 | 高级调试/管理员 |

## 4. 主功能对比

### 4.1 查看图状态和 schema

| 对比项 | 改造前 | 改造后 |
| --- | --- | --- |
| 用户入口 | 独立 schema 查询能力 | `inspect_graph_tool` |
| 返回内容 | 主要是 schema | graph、graphspace、HugeGraph Server 状态、HugeGraph-AI 状态、schema summary、raw schema、顶点/边数量、索引数量、readonly 状态 |
| 降级行为 | 部分失败容易影响整体判断 | best-effort，部分统计失败时保留其他状态并给 warnings |
| 典型用途 | 查看 schema | 连接后第一步检查整体图状态 |

主要改造：

- 增加 `include_raw_schema` 参数。
- 输出 `simple_schema` 和 `raw_schema`。
- 增加 `vertex_count`、`edge_count`、`index_status`。
- 增加 HugeGraph-AI 可用性检查。
- 增加统一 envelope 和 `meta`。

### 4.2 查询图

| 对比项 | 改造前 | 改造后 |
| --- | --- | --- |
| 用户入口 | 自然语言问图、Gremlin 生成、只读 Gremlin 执行分散 | `query_graph_tool` |
| 模式 | 多工具组合 | `mode="text"`、`mode="generate"`、`mode="gremlin"` |
| 生成 Gremlin | 单独工具 | 合并到查询图能力中 |
| 执行生成结果 | 语义不集中 | 默认只生成；只有 `execute=true` 且判定只读时才执行 |
| 危险查询 | 容易依赖调用方判断 | unsafe/uncertain Gremlin 默认拒绝 |
| GraphRAG | 主链路曾不稳定 | 可用但不作为推荐主路径，适合作为高级/实验证据召回 |

主要改造：

- 把自然语言问图、自然语言生成 Gremlin、直接只读 Gremlin 合并为一个查询入口。
- `mode="generate"` 默认不执行。
- 生成并执行时先做只读安全判定。
- 对不确定查询返回 `UNSAFE_GREMLIN`。
- 兼容 HugeGraph-AI 不同返回字段。
- GraphRAG 链路保留，但实际使用中推荐优先走“自然语言生成 Gremlin -> 只读执行”。

已验证示例：

- 查询所有 person 名字成功。
- 自然语言生成 `g.V().hasLabel('person').values('name')` 并执行成功。
- 不确定安全的 Gremlin 查询会被拒绝。

### 4.3 设计和管理 schema

| 对比项 | 改造前 | 改造后 |
| --- | --- | --- |
| 用户入口 | 设计 schema 和执行 schema 操作分散 | `manage_schema_tool` |
| 模式 | 多个底层能力 | `design`、`validate`、`dry_run`、`apply` |
| 真实修改 | 容易直接进入执行 | 必须 dry-run、返回 `plan_hash`、再 `confirm=true` |
| readonly | 保护不集中 | readonly 下拒绝 schema apply |
| 校验 | 基础校验 | 加强属性、点类型、边类型、主键、边端点、索引等语义校验 |

主要改造：

- 收敛 schema 设计、校验、dry-run、apply。
- 使用 `create_property_key`、`create_vertex_label` 等明确 operation 类型。
- `apply` 必须携带匹配的 `plan_hash`。
- 删除 schema 不作为当前支持能力。
- README 和中文 README 已按新 schema 操作示例更新。

### 4.4 管理图数据

| 对比项 | 改造前 | 改造后 |
| --- | --- | --- |
| 用户入口 | 抽图、ingest、表格导入、更新/删除分散或依赖 Gremlin | `manage_graph_data_tool` |
| 自然语言抽图 | 单独抽取，不写入 | `mode="extract"`，默认只返回候选 `graph_data` |
| 结构化导入 | ingest 路径 | `mode="import"`，进入统一安全链 |
| 表格导入 | 不完整或独立 | `mode="table"`，复用 table mapping |
| SQL 表导入 | 原来没有直接可用路径 | `mode="sql_preview"`、`sql_mapping_suggest`、`sql_import"` |
| 更新数据 | 主要靠直接写 Gremlin | `mode="update"`，结构化 change_plan |
| 删除数据 | 主要靠直接写 Gremlin | `mode="delete"`，结构化 change_plan |
| 安全链路 | 不统一 | validate -> dry-run -> plan_hash -> confirm -> execute |

主要改造：

- 新增统一中间格式 `graph_change_plan`。
- `graph_data` 可转换为 `create_vertex`、`create_edge`。
- `update_vertex`、`update_edge`、`delete_vertex`、`delete_edge` 进入高层管理入口。
- 写入前读取 live schema 做校验。
- 顶点主键完整性校验改为基于 live schema。
- 边 source/target 可解析性纳入校验。
- 更新/删除 dry-run 统计 `matched_count`，并修复 HugeGraph 嵌套 count 结果解析。
- 真实写入必须 `confirm=true` 和匹配 `plan_hash`。

已验证示例：

- 自然语言抽图成功。
- 结构化图数据真实写入成功。
- `table_data` 导入 dry-run 成功。
- update/delete dry-run 和真实执行成功。
- 删除测试顶点和边后可复查无残留。

## 5. SQL 表导入改造

SQL 能力是后续在“管理图数据”能力下新增的确定性数据集成功能。

### 5.1 改造前

改造前没有直接从 SQL 数据源导入图数据的 MCP 主路径。用户需要自己：

1. 执行 SQL。
2. 导出 rows。
3. 手动拼成 `table_data`。
4. 再调用表格导入或 graph_data 导入。

### 5.2 改造后

当前已支持 SQLite 第一阶段：

| SQL mode | 作用 |
| --- | --- |
| `sql_preview` | 读取 SQLite 表结构或 SELECT 查询结果，不写图 |
| `sql_mapping_suggest` | 根据 SQL columns 生成可编辑 mapping 建议 |
| `sql_import` | 执行只读 SQL，转成 `table_data`，再复用现有导入链路 |

SQL 导入链路：

```text
SQLite SELECT
-> table_data
-> mapping
-> graph_data
-> change_plan
-> dry-run
-> plan_hash
-> confirm
-> 写入 HugeGraph
```

已新增配置：

```text
HUGEGRAPH_MCP_SQL_ENABLED
HUGEGRAPH_MCP_SQLITE_ALLOWLIST
HUGEGRAPH_MCP_SQL_MAX_PREVIEW_ROWS
HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS
HUGEGRAPH_MCP_SQL_TIMEOUT_SECONDS
```

安全限制：

- SQL 能力默认关闭。
- SQLite 文件必须在 allowlist 中。
- 使用只读 SQLite 连接。
- 只允许单条 `SELECT` 或 `WITH ... SELECT`。
- 拒绝 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`CREATE`、`REPLACE`、`ATTACH`、`DETACH`。
- `sql_import` 真实写入仍受 readonly、dry-run、`plan_hash`、`confirm=true` 保护。

已验证示例：

- `sql_preview` 成功读取本地 `retrieval.sqlite3`。
- `sql_mapping_suggest` 成功生成 mapping 建议。
- `sql_import dry_run` 成功生成 3 个 `webpage` 顶点计划。
- 使用 `WITH ... VALUES` 临时 SQL 表真实写入 2 个 person 顶点和 1 条 colleague 边成功。
- `DROP TABLE chunks;` 被拒绝为 `UNSAFE_SQL`。

## 6. 安全机制变化

### 6.1 readonly 和 allow_ai 分离

| 对比项 | 改造前 | 改造后 |
| --- | --- | --- |
| readonly | 曾影响 AI 能力开关 | `HUGEGRAPH_MCP_READONLY` 只控制图侧写入 |
| allow_ai | 与 readonly 存在耦合 | `HUGEGRAPH_MCP_ALLOW_AI` 独立控制 HugeGraph-AI 调用 |
| 两者同时为 true | 不够清晰 | 支持 AI 辅助读/抽取，同时拒绝写入 |

当前语义：

- `HUGEGRAPH_MCP_READONLY=true`：拒绝 schema apply、图数据写入、直接写 Gremlin、索引刷新。
- `HUGEGRAPH_MCP_ALLOW_AI=true`：允许自然语言 Gremlin 生成、GraphRAG、自然语言抽图。

### 6.2 dry-run / plan_hash / confirm

| 对比项 | 改造前 | 改造后 |
| --- | --- | --- |
| 写入前预览 | 不统一 | schema 和图数据写入统一 dry-run |
| 确认机制 | 不统一 | `confirm=true` 必须显式传入 |
| 计划绑定 | 不统一 | `plan_hash` 绑定计划内容、目标图、schema 上下文 |
| hash mismatch | 不统一 | 拒绝执行，要求重新 dry-run |

当前写入路径：

```text
validate
-> dry-run
-> plan_hash
-> confirm
-> execute
-> verify / query validation
```

### 6.3 Gremlin 安全

| 对比项 | 改造前 | 改造后 |
| --- | --- | --- |
| Gremlin 读写边界 | 更依赖用户或工具入口 | 只读入口默认拒绝不确定 traversal |
| 生成 Gremlin | 生成和执行容易混用 | 默认只生成；执行需 `execute=true` |
| 直接写 Gremlin | 普通路径容易误用 | 标记为高级调试/管理员能力，仍受 readonly guard |

## 7. 输出结构变化

改造后主能力统一返回 envelope：

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
    "readonly": false,
    "duration_ms": 0
  }
}
```

收益：

- Agent 可以稳定判断成功/失败。
- 错误类型结构化，例如 `UNSAFE_GREMLIN`、`UNSAFE_SQL`、`CONFIRM_REQUIRED`、`PLAN_HASH_MISMATCH`、`SCHEMA_MISMATCH`。
- warnings 和 next_actions 可指导下一步。
- meta 提供 request_id、graph、graphspace、readonly、耗时等可观测信息。

## 8. 文档变化

新增或更新：

| 文件 | 变化 |
| --- | --- |
| `hugegraph-mcp/README.md` | 按主功能重写，补充权限模型、SQL/AI/readonly 配置说明 |
| `hugegraph-mcp/README.zh-CN.md` | 新增中文 README |
| `requirements.md` | 定义用户主功能收敛需求 |
| `blocking-fixes-plan.md` | 定义主功能阻断项修复计划 |
| `manage-graph-data-improvement-plan.md` | 定义图数据管理能力升级计划 |
| `manage-graph-data-prd.md` | 定义管理图数据 PRD |
| `sql-table-import-prd.md` | 定义 SQL 表导入 PRD |

## 9. 测试和验收变化

改造后新增或补强了以下测试方向：

| 测试方向 | 当前状态 |
| --- | --- |
| 统一入口路由测试 | 已有 |
| schema 管理测试 | 已有 |
| 图数据 import/update/delete 测试 | 已有 |
| SQL table 适配测试 | 已有 |
| readonly / allow_ai 配置测试 | 已有 |
| Gremlin 安全拒绝测试 | 已有 |
| live MCP 功能测试 | 已在本地多轮验证 |

最近一次本地全量回归：

```text
uv run --project .\hugegraph-mcp pytest .\hugegraph-mcp\tests -q
221 passed
```

最近一次 MCP live 验证覆盖：

- 查看图状态和 schema。
- 只读 Gremlin 查询。
- 自然语言生成 Gremlin 并执行。
- GraphRAG 调用。
- schema validate / dry-run / confirm guard。
- 自然语言抽图。
- graph_data 导入真实写入。
- table_data 导入 dry-run。
- update/delete dry-run 和真实执行。
- SQL preview。
- SQL mapping suggest。
- SQL import dry-run。
- SQL import 真实写入。
- SQL 危险语句拒绝。
- VID embedding refresh。

## 10. 当前用户可体验的新功能

相比最开始改造前，当前用户能直接体验到：

1. 一次性查看图状态、schema、计数、AI 状态和 readonly 状态。
2. 用一个查询入口完成自然语言问图、自然语言生成 Gremlin、只读 Gremlin 执行。
3. 生成 Gremlin 默认不执行，降低误操作风险。
4. schema 设计、校验、dry-run、apply 使用统一入口。
5. 从自然语言抽取图数据，默认不写入。
6. 用结构化 `graph_data` 安全导入图。
7. 用 `table_data + mapping` 导入图。
8. 用 SQLite SQL 查询结果导入图。
9. 对图数据执行高层 update/delete，不需要直接写 Gremlin。
10. 所有真实写入前都有 dry-run、`plan_hash`、`confirm=true`。
11. readonly 和 allow_ai 可以独立控制。
12. 危险 Gremlin 和危险 SQL 会被拒绝。
13. 中文 README 和英文 README 都有当前能力说明。

## 11. 当前限制

以下不是回归问题，而是当前阶段的边界：

- GraphRAG 可用，但不建议作为查询图主路径；更推荐自然语言生成 Gremlin 后只读执行。
- SQL 第一阶段只支持 SQLite，不支持 MySQL/PostgreSQL 等远程数据库。
- SQL mapping suggestion 仍较基础，真实导入时建议用户显式提供 mapping。
- 大规模 SQL 导入不是完整 ETL；当前适合受控批量，受 `HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS` 限制。
- schema 删除、自动回滚、断点续传、完整审计系统不在当前范围。
- `execute_gremlin_write_tool` 仍暴露，但定位是高级调试/管理员能力，不是普通用户主路径。

## 12. 改造范围总结

本轮改造覆盖的主要文件和模块包括：

| 范围 | 说明 |
| --- | --- |
| `server.py` | 收敛主入口，接入 SQL mode，保留兼容/调试工具 |
| `inspect_graph.py` | 图状态、schema、计数、AI 状态检查 |
| `query_graph.py` | 统一自然语言问图、生成 Gremlin、只读 Gremlin 执行 |
| `manage_schema.py` | schema 设计、校验、dry-run、apply |
| `manage_graph_data.py` | graph_data、table、SQL、update、delete 安全链 |
| `extract_graph_data.py` | 自然语言抽图和默认中文抽取 prompt |
| `ingest_graph_data.py` | graph payload 校验和导入兼容 |
| `import_table.py` | table_data 到 graph_data 映射 |
| `sql_table.py` | SQLite preview、只读 SQL 校验、SQL 结果转 table_data |
| `guard.py` | capability guard 和 readonly 保护 |
| `config.py` | readonly、allow_ai、SQL 配置 |
| `envelope.py` | 统一 envelope 和错误类型 |
| `tests/` | 主功能、SQL、安全、配置、图数据管理测试 |
| `README.md` / `README.zh-CN.md` | 用户文档按当前能力更新 |

总体上，改造不是简单增加几个工具，而是把 MCP 从“底层能力集合”调整成“以图数据库用户任务为中心的高层能力接口”，并补齐了写入、安全、确认、文档和测试闭环。
