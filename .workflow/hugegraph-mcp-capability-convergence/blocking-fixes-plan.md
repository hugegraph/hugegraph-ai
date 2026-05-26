# HugeGraph MCP 主功能收敛前阻断项修复计划

## 1. 背景

当前 HugeGraph MCP 的用户能力计划收敛为四个主功能：

1. 查看图状态和 schema。
2. 查询图。
3. 设计和管理 schema。
4. 通过自然语言或结构化 SQL 表导入图数据。

在正式推进主功能收敛前，需要先修复会直接阻断主功能验收的缺陷。尤其是自然语言问图链路、统一入口和返回结构、写入与 schema 的安全边界。如果这些问题不先解决，后续入口收敛只会把不稳定或不安全的能力包装到更高层。

本计划只覆盖主功能阻断项，不要求清理所有历史缺陷。旧调试入口、非 V1 能力、自动回滚、删除 schema、自动刷新 embedding 等问题不作为本轮优先修复范围。

## 2. 修复原则

- 优先修复会导致四个主功能不可用、不安全或无法验收的问题。
- 不优先修复只影响旧入口、调试入口或非当前阶段能力的问题。
- 先让“查询图”真实可用，再做入口收敛。
- 所有写入和 schema 修改必须先具备 readonly、dry-run、confirm、plan hash 和 schema 校验保护。
- 每个修复都必须有对应的单元测试或端到端验收用例。

## 3. 阶段 0：修自然语言问图阻断项

### 目标

让“查询图”主功能先真正可用，避免后续只是在高层入口包装一个不可用的自然语言问答链路。

### 任务表

| 任务 | 修改点 | 验收标准 |
|---|---|---|
| 修 AI 健康检查误判 | `hugegraph_ai_client.health_check` / `inspect_graph` | `/health` 404 时不直接判定 AI 完全不可用；能通过 `/openapi.json`、`/graph-index-info` 或 `/` 判断服务可访问 |
| 修 MCP 调 RAG 参数 | `query_graph.py` | 请求 `/rag/graph` 时传 `max_graph_items`、`gremlin_tmpl_num=-1`、`client_config`；不再只传后端不使用的 `graph/graphspace/max_context_items` |
| 修 `/rag` 返回解析 | `query_graph.py` | 能解析 `answer`、`graph_only`、`vector_only`、`graph_vector_answer` 等字段，不再因为没有 `answer` 字段就返回空 |
| 规避 `NoneType.exist` | MCP 侧先显式传 `gremlin_tmpl_num=-1`；后端再补防御 | 默认自然语言问图不触发 Gremlin 示例索引空对象错误 |
| 增加降级输出 | `query_graph.py` | RAG 空结果时返回明确原因、证据和 `next_actions`，而不是看起来成功但 `answer=null` |

### 必须验收的用例

- 用户问“James 的朋友的职业是什么”，系统返回 Sarah / 律师，并带图证据。
- 用户问“图中有哪些人物”，系统至少能返回图中人物，或明确说明宽泛问题需要更具体查询。
- HugeGraph-AI 服务正常但 `/health` 不存在时，图状态不误报 AI 完全不可用。
- HugeGraph-AI 返回 `graph_only` 或 `vector_only` 字段时，MCP 能映射成统一答案。
- RAG 返回空结果时，MCP 返回明确 warning 或 next actions。

## 4. 阶段 1：统一入口和返回结构

### 目标

四个主功能共用一致的 envelope、错误、warnings 和 next actions，避免每个功能重复处理返回格式和错误语义。

### 任务表

| 任务 | 修改点 | 验收标准 |
|---|---|---|
| 定义主功能输出规范 | 文档 + envelope helper | 四个主功能统一包含 `ok`、`data`、`error`、`warnings`、`next_actions`、`meta` |
| 统一状态字段 | `inspect`、`query`、`schema`、`ingest` 相关工具 | `meta` 中稳定包含 `request_id`、`graph`、`graphspace`、`readonly`、`duration_ms` |
| 统一错误类型 | envelope / error handling | 连接失败、AI 不可用、schema 不匹配、只读拒绝、安全拒绝都能结构化返回 |
| 统一 next actions | 各主功能 | 失败时给出下一步，例如“重新 dry-run”“检查 AI 服务”“改用只读查询” |
| 降级底层入口展示 | server 工具描述 / README | 普通用户文档只突出四个主功能，底层写入和底层 schema 操作标为高级调试 |

### 必须验收的用例

- 查询图失败时不是空答案，而是结构化错误或明确 warning。
- schema dry-run、导入 dry-run、AI 不可用都能给出一致格式。
- README 按四个主功能组织说明，而不是按底层工具堆叠。
- 所有主功能返回中都包含可追踪的 `request_id`。

## 5. 阶段 2：写入和 schema 安全边界

### 目标

避免后续出现“能写但不安全”的半成品。导入图数据和 schema 管理必须先具备统一安全底线。

### 任务表

| 任务 | 修改点 | 验收标准 |
|---|---|---|
| 固化 readonly guard | guard / schema / ingest / refresh / write | `readonly=true` 时所有写入、schema 修改、索引刷新都拒绝 |
| 固化 dry-run + confirm | schema 管理、图数据导入 | 没有 dry-run 计划不能直接 apply 或 write |
| 加强 plan hash | `manage_schema`、`ingest_graph_data` | hash 输入包含 graph、graphspace、live schema 摘要、operations 或 payload |
| apply/write 校验 hash | schema apply、数据写入 | `plan_hash` 缺失或不匹配时拒绝执行 |
| 强化 schema 校验 | ingest 校验 | 顶点主键、属性类型、边 source/target 可解析、label 合法性都在写入前校验 |
| 标记底层调试写入口 | server 描述 / README | 底层写 Gremlin、底层 schema 操作不作为普通主路径推荐 |

### 必须验收的用例

- `readonly=true` 时写 Gremlin、schema apply、数据写入、embedding 刷新全部被拒绝。
- 未 confirm 时拒绝写入。
- `plan_hash` 不匹配时拒绝写入。
- payload 缺主键时拒绝导入。
- 边端点不存在时拒绝导入。
- dry-run 不产生任何写入。

## 6. 阶段 3：回归测试和端到端验收

### 目标

确认修复覆盖主功能路径，而不是只修复单个局部用例。

### 测试范围

| 测试范围 | 必测场景 |
|---|---|
| 单元测试 | RAG 参数构造、返回字段解析、health fallback、错误 envelope |
| MCP live 测试 | 查看状态、查 schema、自然语言问图、只读 Gremlin、危险 Gremlin 拒绝 |
| schema 安全测试 | dry-run、confirm 缺失、hash mismatch、readonly 拒绝 |
| ingest 安全测试 | 缺主键、类型错误、边端点不存在、dry-run 不写入、confirm 写入 |
| 回归测试 | `uv run pytest` 全量通过 |

### 必须运行的命令

```powershell
cd D:\Code\agent_learning\hugegraph-ai\hugegraph-mcp
uv run pytest
```

如涉及 HugeGraph-AI 或 MCP live 链路，还需要补充真实服务验收：

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8001/openapi.json -UseBasicParsing
Invoke-WebRequest -Uri http://127.0.0.1:8001/graph-index-info -UseBasicParsing
```

## 7. 推荐执行顺序

1. 先修自然语言问图四个阻断项。
2. 跑 live 验收，确认“查询图”可用。
3. 再统一 envelope 和主功能输出。
4. 然后补写入/schema 安全边界。
5. 最后补文档和完整回归测试。

## 8. 暂不优先处理的事项

以下事项不作为本轮阻断项：

- 底层调试入口体验完全统一。
- 自动理解 SQL 数据库并自动建模。
- 自动连接 MySQL / PostgreSQL 等外部数据库。
- 写入后自动刷新 embedding。
- 删除 schema。
- 自动回滚、批次清理、批量删除。
- 大规模导出或备份。

这些能力可以在四个主功能稳定后作为后续增强项规划。
