# HugeGraph MCP V1 Code Prune PRD

## 1. 背景

当前 MCP-V1 分支已经把 V2/未来能力从用户公开入口隐藏或默认禁用，但仓库内仍保留了部分 V2/未来能力的实现代码、测试和配置项。

这会带来两个问题：

- V1 PR 规模过大，评审者需要同时阅读 V1 稳定能力和后续能力实现。
- V1 边界不够清晰，隐藏代码、测试和配置容易让人误以为 V2 能力已经属于 V1 交付范围。

因此，V1 分支应只保留 V1 相关代码。V2 及以后能力从 V1 分支删除，后续按独立 PR 重新提交。

## 2. 目标

- 将 MCP-V1 分支裁剪为只包含 V1 必需代码、文档和测试。
- 删除 V2/未来能力的源码、测试、配置和文档描述。
- 降低 V1 PR 的 diff 规模和评审复杂度。
- 保证 V1 公开工具契约、readonly 默认安全、plan_hash 安全链和 disabled feature 行为不退化。

## 3. 非目标

- 不在本次 V1 PR 中实现或保留 GraphRAG 问答能力。
- 不在本次 V1 PR 中实现或保留 SQL/SQLite 数据源导入能力。
- 不在本次 V1 PR 中实现或保留 table import 映射能力。
- 不在本次 V1 PR 中实现或保留 graph data update 能力。
- 不在本次 V1 PR 中实现或保留 schema apply 执行能力。
- 不改变 V1 已确认的公开稳定工具行为。

## 4. V1 保留范围

### 4.1 保留的 MCP 工具

V1 保留 8 个稳定用户工具：

- `inspect_graph_tool`
- `generate_gremlin_tool`
- `execute_gremlin_read_tool`
- `extract_graph_data_tool`
- `design_schema_tool`
- `apply_schema_tool`
- `import_graph_data_tool`
- `delete_graph_data_tool`

V1 继续保留 2 个已注册但默认阻断的 admin/debug 工具，除非后续决定进一步缩小公开面：

- `execute_gremlin_write_tool`
- `refresh_vid_embeddings_tool`

保留原因：这两个工具已经属于当前 V1 注册契约的一部分，并且默认由 `HUGEGRAPH_MCP_ADMIN_MODE=false` 返回 `FEATURE_DISABLED`。它们不是 V2 功能，但必须在 PR 描述中标为 admin/debug gated，不作为普通用户主流程宣传。

### 4.2 保留的内部能力

- MCP 配置读取：HugeGraph URL、graph、graphspace、user、password、readonly、allow_ai、AI URL、timeout。
- 统一 envelope：`ok/data/error/warnings/next_actions/meta`。
- readonly/admin/confirm 权限守卫。
- Gremlin read safety policy。
- `plan_hash` 生成和校验。
- live schema 获取和 schema summary。
- V1 schema design / validate / dry_run。
- V1 graph_data extract / ingest / delete。
- V1 受控删除只支持精确 `delete_vertex` / `delete_edge`。

## 5. V1 删除范围

### 5.1 GraphRAG 问答能力

删除：

- `hugegraph_mcp/tools/query_graph.py`
- `tests/test_query_graph.py`

同步删除或收敛：

- `HUGEGRAPH_MCP_MAX_CONTEXT_ITEMS`
- `HUGEGRAPH_MCP_ENABLE_GRAPHRAG_EXPERIMENTAL`
- README / 中文 README 中 GraphRAG 预留配置描述
- `tests/test_config.py` 中 GraphRAG 配置断言

后续归属：V2 GraphRAG PR。

### 5.2 SQL/SQLite 数据源能力

删除：

- `hugegraph_mcp/tools/sql_modes.py`
- `hugegraph_mcp/tools/sql_table.py`
- `tests/test_sql_table.py`

同步删除或收敛：

- `HUGEGRAPH_MCP_SQL_ENABLED`
- `HUGEGRAPH_MCP_SQLITE_ALLOWLIST`
- `HUGEGRAPH_MCP_SQL_MAX_PREVIEW_ROWS`
- `HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS`
- `HUGEGRAPH_MCP_SQL_TIMEOUT_SECONDS`
- README / 中文 README 中 SQL 预留配置描述
- `ErrorType.UNSUPPORTED_SQL_SOURCE`
- `ErrorType.UNSAFE_SQL`

后续归属：V2 SQL import PR。

### 5.3 Table import 映射能力

删除：

- `hugegraph_mcp/tools/import_table.py`
- `tests/test_import_table.py`

保留：

- `import_graph_data_tool(mode="table")` 在 V1 中继续返回 `FEATURE_DISABLED`。
- 相关 disabled 行为测试应保留或迁移到 `tests/test_import_graph_data_tool.py`。

后续归属：V2 table import PR。

### 5.4 Graph data update 能力

删除或收敛：

- `manage_graph_data(mode="update")`
- `update_vertex`
- `update_edge`
- `_update_vertex_query`
- `_update_edge_query`
- update 相关 validation、dry-run、execute 分支
- `tests/test_manage_graph_data.py` 中 update 相关用例

保留：

- `manage_graph_data(mode="import")`
- `manage_graph_data(mode="delete")`
- `create_vertex`
- `create_edge`
- `delete_vertex`
- `delete_edge`
- dry-run / plan_hash / confirm / readonly 保护

后续归属：V2 graph data update PR。

### 5.5 Schema apply 执行能力

删除或收敛：

- `manage_schema(mode="apply")` 的执行分支
- `schema_tools.execute_schema_operations`
- schema apply 的 confirm / plan_hash / execute 测试
- `tests/test_execute_schema_operations.py`
- `tests/test_manage_schema.py` 中 apply 执行相关用例

保留：

- `apply_schema_tool(mode="apply")` 直接返回 `FEATURE_DISABLED`
- `manage_schema(mode="design")`
- `manage_schema(mode="validate")`
- `manage_schema(mode="dry_run")`
- create-only schema validation 和 dry-run plan hash

后续归属：V2 schema apply PR。

## 6. 文档范围

V1 README 只描述：

- V1 稳定工具列表。
- admin/debug gated 工具默认禁用。
- readonly 默认安全。
- AI 调用开关。
- graph_data ingest/delete 的 dry-run -> plan_hash -> confirm 链。
- schema validate/dry_run，明确 apply 禁用。
- table import / SQL / GraphRAG / update / schema apply 不属于 V1。

V1 README 不描述：

- GraphRAG 配置项。
- SQL/SQLite 配置项。
- table import 映射流程。
- graph data update 流程。
- schema apply 执行流程。

## 7. 测试范围

V1 必须保留或补齐以下测试：

- MCP tool 注册集合。
- 旧工具不暴露：
  - `query_graph_tool`
  - `manage_schema_tool`
  - `manage_graph_data_tool`
- readonly 默认值和 readonly 守卫。
- admin/debug 工具默认 `FEATURE_DISABLED`。
- `apply_schema_tool(mode="apply")` 返回 `FEATURE_DISABLED`。
- `import_graph_data_tool(mode="table")` 返回 `FEATURE_DISABLED`。
- `generate_gremlin_tool` 只执行只读 Gremlin。
- `execute_gremlin_read_tool` 拒绝写 Gremlin。
- `extract_graph_data_tool` 不写入。
- `import_graph_data_tool(mode="ingest")` dry-run / confirm / plan_hash。
- `delete_graph_data_tool` 精确删除、安全预览、confirm 校验。
- envelope 结构。

删除以下 V2/未来测试：

- `tests/test_query_graph.py`
- `tests/test_sql_table.py`
- `tests/test_import_table.py`
- `tests/test_execute_schema_operations.py`
- update-only 的 `tests/test_manage_graph_data.py` 用例
- schema apply execute-only 的 `tests/test_manage_schema.py` 用例
- GraphRAG/SQL config-only 的 `tests/test_config.py` 用例

## 8. 验收标准

- V1 分支中不存在 GraphRAG 问答源码和测试。
- V1 分支中不存在 SQL/SQLite 源码和测试。
- V1 分支中不存在 table import 映射源码和测试。
- V1 graph data 代码不再支持 `update_vertex` / `update_edge`。
- V1 schema 代码不再执行 schema apply。
- `import_graph_data_tool(mode="table")` 仍返回 `FEATURE_DISABLED`。
- `apply_schema_tool(mode="apply")` 仍返回 `FEATURE_DISABLED`。
- MCP tool list 与 V1 契约一致。
- README/中文 README 没有把 V2 能力作为 V1 配置或用户流程描述。
- `hugegraph-mcp` 全量测试通过。

## 9. 风险

- 删除 update 分支可能影响 delete/import 共享的 validation 和 Gremlin 生成代码，需要逐项收敛而不是整文件删除。
- 删除 schema apply 时要保留 schema validate/dry_run 的 plan hash 逻辑。
- 删除 SQL/table import 后，`import_graph_data_tool(mode="table")` 仍需要保留 disabled stub，避免 API 行为改变为 unknown mode。
- 删除 config 字段后，需要同步更新 README 和 config 测试。

## 10. 回滚策略

- 已创建备份分支：`codex/backup-mcp-v1-20260528-7d93158`。
- 如删除范围过大或影响 V1 测试，可从备份分支恢复对应文件。
- V2 功能后续从备份分支或当前历史中 cherry-pick 到独立 V2 PR。

## 11. 执行计划

### 阶段 1：冻结当前状态

- 确认备份分支存在并指向当前 MCP-V1 基线。
- 保存本 PRD。
- 确认当前 V1 测试基线。

### 阶段 2：删除独立 V2 模块

- 删除 `query_graph.py` 和 `tests/test_query_graph.py`。
- 删除 `sql_modes.py`、`sql_table.py` 和 `tests/test_sql_table.py`。
- 删除 `import_table.py` 和 `tests/test_import_table.py`。
- 运行 import 检查，确认没有残留引用。

### 阶段 3：收敛配置和文档

- 从 `MCPConfig` 删除 GraphRAG/SQL/table-only 配置字段。
- 从 README/README.zh-CN 删除 GraphRAG/SQL 预留配置。
- 更新 `tests/test_config.py`，只保留 V1 配置项。

### 阶段 4：收敛 graph data update

- 从 validation allowlist 删除 `update_vertex` / `update_edge`。
- 删除 update Gremlin 生成函数和 `_write_query` update 分支。
- 将 `manage_graph_data` 支持模式收敛为 `import` / `delete`。
- 删除 update-only 测试，保留 import/delete/dry-run/confirm/plan_hash 测试。

### 阶段 5：收敛 schema apply 执行

- 删除 `manage_schema(mode="apply")` 执行分支。
- 删除 `schema_tools.execute_schema_operations` 或降级为非 V1 私有不可达代码后再删除。
- 删除 schema apply execute 相关测试。
- 保留 `apply_schema_tool(mode="apply")` 的 `FEATURE_DISABLED` 测试。

### 阶段 6：修复引用和测试

- 运行全仓 `git grep`，确认 V2 关键词只出现在 PRD 或 disabled 行为测试中。
- 更新 V1 tool contract 测试。
- 更新 README 断言或文档相关测试。

### 阶段 7：验证

- 运行 V1 关键测试：
  - `uv run pytest tests/test_v1_stable_tools.py tests/test_readonly_mode.py tests/test_import_graph_data_tool.py`
- 运行 MCP 全量测试：
  - `uv run pytest`
- 运行静态检查，如当前项目已有命令：
  - `uv run ruff check .`
  - `uv run ruff format --check .`

### 阶段 8：PR 准备

- PR 标题聚焦 V1：`feat(mcp): add V1 stable tool surface`
- PR 描述列出删除的 V2 能力及后续 PR 计划。
- PR 中不包含 V2 用户功能描述。
- V2 后续 PR 从备份分支或历史中恢复对应模块。
