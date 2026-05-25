# HugeGraph MCP 主功能收敛 — 执行计划

## 决策记录

| 决策点 | 结论 | 日期 |
|--------|------|------|
| 工具收敛策略 | 合并为 4 主入口 + 2 隐藏调试工具 | 2026-05-25 |
| Gremlin 安全判定 | 当前 regex allowlist 方案够用 | 2026-05-25 |
| plan_hash 过期 | 本里程碑跳过 | 2026-05-25 |

## 目标工具面

**4 个主功能入口：**

| 主功能 | 统一入口 tool | 合并的底层函数 |
|--------|-------------|---------------|
| 查看图状态和 schema | `inspect_graph_tool` | `get_live_schema` (内部) |
| 查询图 | `query_graph_tool` | `query_graph_by_text` + `generate_gremlin` + `execute_gremlin_read` |
| 设计和管理 schema | `manage_schema_tool` | `design_schema` + `execute_schema_operations` (内部) |
| 导入图数据 | `import_graph_data_tool` | `extract_graph_data` + `ingest_graph_data` |

**2 个隐藏调试工具：**
- `execute_gremlin_write_tool` (运行时 guard 保护)
- `refresh_vid_embeddings_tool` (运行时 guard 保护)

## 任务列表

### Phase 1：入口收敛 (12 → 6 tools)

| # | 任务 | 涉及文件 | 状态 |
|----|------|---------|------|
| T1 | `get_live_schema_tool` 收敛到 `inspect_graph_tool` | server.py, inspect_graph.py, tests | done |
| T2 | 3 个查询工具合并为 `query_graph_tool` | server.py, tests | done |
| T3 | `design_schema_tool` + `execute_schema_operations_tool` 隐藏 | server.py, tests | done |
| T4 | `extract_graph_data_tool` + `ingest_graph_data_tool` 合并为 `import_graph_data_tool` | server.py, tests | done |

### Phase 2：安全语义加强

| # | 任务 | 涉及文件 | 状态 |
|----|------|---------|------|
| T5 | `validate_schema_operations` 深层语义校验 | manage_schema.py, tests | done |

### Phase 3：新能力

| # | 任务 | 涉及文件 | 状态 |
|----|------|---------|------|
| T6 | 结构化表格导入模块 (CSV/JSON → graph payload) | 新建 tools/import_table.py, tests | todo |

### Phase 4：文档与验收

| # | 任务 | 涉及文件 | 状态 |
|----|------|---------|------|
| T7 | README 按四主功能重写 | README.md | todo |
| T8 | 测试补全 + 全量回归 | tests/ | todo |

## 验收标准 (PRD 对应)

- 4 个主功能统一入口 (U1-U4)
- 统一 envelope 返回 (U9-U10)
- readonly 保护所有写入路径 (S1-S3)
- dry-run → plan_hash → confirm 安全链 (E17-E18, E29)
- schema 语义校验完整 (E16)
- 自然语言问图链路可用 (E9-E10)
- 危险 Gremlin 拒绝 (X4, U12)
- README 四主功能组织 (E32)

## 执行纪律

- 每个 task 单独 commit
- Claude 派发 → Codex 执行 → Claude 审查 → commit
- 派发命令: `python ~/.claude/scripts/codex_workflow.py serial --intent implement --task "..." --dangerous --workspace D:/Code/agent_learning/hugegraph-ai --zh`
