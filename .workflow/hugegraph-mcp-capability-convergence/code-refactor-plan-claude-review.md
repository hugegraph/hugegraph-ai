# HugeGraph MCP 代码重构计划与 Claude Code 审核

日期：2026-05-26

## 背景

当前 `hugegraph-mcp/hugegraph_mcp` 的用户能力已经收敛为：

- 查看图状态和 schema
- 查询图
- 设计和管理 schema
- 从自然语言、结构化图数据、表格或 SQL 导入和管理图数据

代码层面已经可以运行，但维护性仍有提升空间。主要问题集中在：

- `hugegraph_mcp/server.py` 同时负责 FastMCP 工具注册、mode 路由和 SQL 编排。
- `hugegraph_mcp/tools/manage_graph_data.py` 文件过大，包含校验、dry-run、plan hash、Gremlin 查询构造、写入执行、`graph_data` 到 `change_plan` 映射等多个职责。
- schema、SQL、数据导入已经有一定分层，但入口和核心执行文件仍偏重。

本计划目标是做行为保持的结构重构，不改变 MCP 对外工具、参数、返回 envelope、权限模型和用户可见行为。

## 原始重构计划

### Phase 1：建立基线

目标：在重构前固定可比对的行为基线。

执行项：

1. 运行完整测试：

   ```powershell
   uv run --project .\hugegraph-mcp pytest .\hugegraph-mcp\tests -q
   ```

2. 导出 FastMCP 工具列表和参数 schema。

3. 确认以下内容在重构前后不变：

   - MCP 工具名
   - 工具参数名
   - 参数默认值
   - envelope 字段结构
   - readonly / allow_ai / SQL 权限行为

4. 记录当前 git 工作区状态，避免混入无关改动。

### Phase 2：瘦身 `server.py`

目标：让 `server.py` 只负责 MCP 工具注册和轻量路由。

新增文件：

```text
hugegraph_mcp/tools/sql_modes.py
```

迁移内容：

- `_handle_sql_mode`
- `sql_preview`
- `sql_mapping_suggest`
- `sql_import`

保留行为：

- `manage_graph_data_tool` 对外参数不变。
- `server.py` 仍注册同一个 MCP 工具。
- SQL 模式仍通过 `manage_graph_data_tool` 暴露。

收益：

- SQL 编排集中到 SQL 相关模块。
- `server.py` 更接近纯 MCP adapter。
- 后续修改 SQL 导入逻辑不需要频繁碰 MCP 注册入口。

### Phase 3：拆出 `graph_data -> change_plan` 映射

目标：把图数据输入转换成变更计划的逻辑从 `manage_graph_data.py` 中独立出来。

新增文件：

```text
hugegraph_mcp/tools/graph_data_mapping.py
```

迁移内容：

- `graph_data_to_change_plan`
- `_vertex_matches_by_id`
- `_edge_endpoint_match`

兼容要求：

```python
from hugegraph_mcp.tools.manage_graph_data import graph_data_to_change_plan
```

这个旧导入路径必须继续可用。

收益：

- 自然语言抽取、table import、SQL import 复用同一个独立映射模块。
- 后续修复 `outV/inV`、`source/target`、主键匹配等问题时不需要进入 update/delete 执行代码。

### Phase 4：拆分 `manage_graph_data.py`

目标：将大型核心文件拆成职责清晰的内部模块。

原计划拆分：

```text
hugegraph_mcp/tools/change_plan_validation.py
hugegraph_mcp/tools/change_plan_execution.py
hugegraph_mcp/tools/change_plan_hash.py
```

预期职责：

- validation：校验 change plan、schema、字段、主键和边端点。
- execution：生成和执行 Gremlin 写入，做执行后验证。
- hash：生成和校验 plan hash。
- `manage_graph_data.py` 保留高层 orchestration。

### Phase 5：增加内部类型

目标：在不改变外部 JSON 的前提下，增加内部类型说明。

候选类型：

- `GraphData`
- `GraphChangePlan`
- `GraphOperation`
- `TableData`
- `TableMapping`
- `SqlSource`

优先考虑 `TypedDict` 或轻量内部类型，不改变 FastMCP 参数 schema。

### Phase 6：测试策略

每个阶段执行：

```powershell
uv run --project .\hugegraph-mcp pytest .\hugegraph-mcp\tests -q
```

额外验证：

- FastMCP 工具列表不变。
- FastMCP 工具参数 schema 不变。
- SQL 三种 mode 行为不变。
- `graph_data_to_change_plan` 的旧导入路径不变。
- `manage_graph_data_tool` 的 import / table / sql_import / update / delete 路由不变。

## Claude Code 审核摘要

Claude Code 审核模式：`refactor`

审核目标：

- `hugegraph-mcp/hugegraph_mcp/server.py`
- `hugegraph-mcp/hugegraph_mcp/tools/manage_graph_data.py`
- `hugegraph-mcp/hugegraph_mcp/tools/sql_table.py`
- `hugegraph-mcp/hugegraph_mcp/tools/import_table.py`

审核输出文件：

```text
runtime/claude_reviews/20260526071907928124_review.md
```

首次审核尝试失败，原因是 Claude Code session ID 被占用：

```text
runtime/claude_reviews/20260526071827230115_review.md
Error: Session ID ... is already in use.
```

已使用 `--isolated` 重试并成功获得审核结果。

### Claude 认可的部分

1. Phase 1 是必要基线。

   Claude 建议在 FastMCP 工具 schema 快照之外，也快照 `manage_graph_data.py` 的公共函数签名，例如：

   - `validate_graph_change_plan`
   - `dry_run_graph_change_plan`
   - `execute_graph_change_plan`
   - `calculate_graph_change_plan_hash`
   - `graph_data_to_change_plan`

2. Phase 2 可以现在做。

   `_handle_sql_mode` 是纯编排函数，没有依赖 `server.py` 的闭包或全局状态，适合迁移到 `tools/sql_modes.py`。

3. Phase 3 可以做，但要注意依赖方向。

   `graph_data_to_change_plan` 当前依赖 `_change_plan_from_operations`。Claude 建议把这个一行 helper 一起移动到 `graph_data_mapping.py`，不要让 `graph_data_mapping.py` 反向 import `manage_graph_data.py`，否则会形成错误的依赖方向。

### Claude 指出的风险

1. Phase 4 原计划过于粗略。

   `manage_graph_data.py` 中有一些 helper 同时被 dry-run 和 execution 使用，不能简单归到 validation 或 execution 任一侧。

   例如：

   - `_vertex_match_query`
   - `_edge_match_query`
   - `_source_vertex_match_query`
   - `_target_vertex_match_query`
   - `_write_query`
   - `_read_count`
   - `_read_values`
   - `_extract_count_value`

2. Phase 4 有循环 import 风险。

   如果 validation、execution、hash 互相引用共享 helper，很容易形成：

   ```text
   validation -> execution -> validation
   ```

   或者让 entry point 模块反向被底层模块依赖。

3. FastMCP schema 快照不能覆盖私有函数行为。

   例如 `_edge_endpoint_match`、`_vertex_matches_by_id` 的行为变化不会被 MCP 工具 schema 检测到，需要直接单元测试覆盖。

4. 当前工作区有未提交改动。

   Claude 建议在做 Phase 4 这种大拆前，先提交或至少稳定当前功能改动，否则结构重构和功能修复会混在一起，增加冲突和回滚难度。

### Claude 建议的 Phase 4 新拆分

Claude 建议将 Phase 4 拆得更细，并使用内部模块名：

```text
manage_graph_data.py
  -> 只保留入口 orchestration

_change_plan_types.py
  -> ALLOWED_OPS
  -> VERTEX_OPS
  -> EDGE_OPS
  -> WRITE_OPS
  -> MODE_OPS
  -> GraphChangePlan
  -> _operations()
  -> _change_plan_from_operations()
  -> _validation_error()

_change_plan_validation.py
  -> validate_graph_change_plan
  -> schema helpers
  -> field validators

_change_plan_queries.py
  -> _vertex_match_query
  -> _edge_match_query
  -> _source_vertex_match_query
  -> _target_vertex_match_query
  -> _read_count
  -> _read_values
  -> _extract_count_value

_change_plan_hash.py
  -> calculate_graph_change_plan_hash

_change_plan_execution.py
  -> dry_run_graph_change_plan
  -> execute_graph_change_plan
```

Claude 建议使用 `_` 前缀，明确这些是内部模块，不是新增用户工具。

### Claude 建议的测试补充

Phase 2：

- 直接测试 `sql_modes._handle_sql_mode(...)` 或其内部路由对三种 SQL mode 的行为：
  - `sql_preview`
  - `sql_mapping_suggest`
  - `sql_import`
- 保留通过 `manage_graph_data_tool` 的集成测试，确保 MCP 入口仍然可用。

Phase 3：

- 保留已有 `graph_data_to_change_plan` 行为测试：
  - 映射 create vertex / create edge
  - `outV/inV` 映射到顶点属性
  - 数字 id 和字符串 id 归一化
- 新增兼容导入测试：

  ```python
  from hugegraph_mcp.tools.manage_graph_data import graph_data_to_change_plan
  ```

  验证该导入仍然可用。

Phase 4：

- 拆测试文件或按职责重组：
  - `test_change_plan_validation.py`
  - `test_change_plan_hash.py`
  - `test_change_plan_execution.py`
  - `test_manage_graph_data.py` 只保留入口 orchestration 测试

### Claude 建议暂缓的部分

1. 暂缓 Phase 4，直到当前功能改动已提交或至少有清晰边界。

2. 不建议现在给 `GraphChangePlan` 强行加复杂 `TypedDict`。

   原因：

   - 当前结构是 `dict[str, list[dict[str, Any]]]`
   - 操作类型较多，递归/联合类型会增加维护负担
   - 现有运行时校验已经承担主要安全职责

3. 不建议把 `_handle_sql_mode` 改成公开 API。

   即使移到 `sql_modes.py`，也应保持内部编排函数属性。

## 采纳后的修订计划

### 第一轮只做低风险重构

先执行 Phase 1、Phase 2、Phase 3，不做 Phase 4/5。

原因：

- 当前工作区已有多处未提交功能改动。
- Phase 2/3 风险低，收益明确。
- Phase 4 是大拆，应该单独作为后续重构任务。

### 修订后的 Phase 1

增加公共函数签名快照：

- `manage_graph_data`
- `validate_graph_change_plan`
- `dry_run_graph_change_plan`
- `execute_graph_change_plan`
- `calculate_graph_change_plan_hash`
- `graph_data_to_change_plan`

同时保留原本 FastMCP tool schema 快照。

### 修订后的 Phase 2

新增：

```text
hugegraph_mcp/tools/sql_modes.py
```

迁移：

- `_handle_sql_mode`

导入依赖：

- `envelope_ok`
- `envelope_err`
- `preview_sql`
- `execute_select_to_table_data`
- `import_table_data`
- `suggest_table_mapping`
- `manage_graph_data`
- `graph_data_to_change_plan`

注意：

- `server.py` 只调用 `_handle_sql_mode(...)`。
- 不改变 `manage_graph_data_tool` 参数。
- 不改变 `sql_preview`、`sql_mapping_suggest`、`sql_import` 的返回。

### 修订后的 Phase 3

新增：

```text
hugegraph_mcp/tools/graph_data_mapping.py
```

迁移：

- `graph_data_to_change_plan`
- `_vertex_matches_by_id`
- `_edge_endpoint_match`
- `_change_plan_from_operations`

注意：

- `graph_data_mapping.py` 不 import `manage_graph_data.py`。
- `manage_graph_data.py` re-export `graph_data_to_change_plan`。
- `sql_modes.py` 优先从 `manage_graph_data.py` 导入 `graph_data_to_change_plan`，保持兼容路径稳定。

### Phase 4 暂缓后的新计划

Phase 4 单独排期，目标模块：

```text
hugegraph_mcp/tools/_change_plan_types.py
hugegraph_mcp/tools/_change_plan_validation.py
hugegraph_mcp/tools/_change_plan_queries.py
hugegraph_mcp/tools/_change_plan_hash.py
hugegraph_mcp/tools/_change_plan_execution.py
```

执行条件：

- 当前功能修复已提交或至少有明确基线。
- Phase 2/3 已通过全量测试。
- 已增加内部函数行为测试。

### Phase 5 调整

不在第一轮做类型系统重构。

后续如果需要增加类型，优先从局部 `TypedDict` 或普通 dataclass 辅助开始，不强行给所有 `GraphChangePlan` 操作建复杂类型层级。

## 最终建议

建议当前只执行：

1. Phase 1：测试和快照基线
2. Phase 2：抽出 SQL mode 编排
3. Phase 3：抽出 `graph_data` 映射

暂缓：

1. 大规模拆分 `manage_graph_data.py`
2. 引入复杂类型系统
3. 重命名或公开内部 helper

这样可以在不改变用户能力、不影响 MCP 工具 schema 的前提下，先降低 `server.py` 和 `manage_graph_data.py` 的复杂度，并为后续更彻底的 change plan 拆分打基础。
