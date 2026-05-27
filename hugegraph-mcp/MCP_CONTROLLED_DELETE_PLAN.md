# HugeGraph MCP Controlled Delete Plan

> 目标：在 MCP V1 上线版本中增加“可控删除”能力，同时保持当前 V1 的安全边界：小工具、明确职责、默认只读、dry-run/plan_hash/confirm、禁止用户绕过 MCP 风控。

## 1. 背景

当前 MCP V1 已经将用户可见写入收口到稳定工具面，普通用户不直接使用 `manage_graph_data_tool`、`query_graph_tool`、`manage_schema_tool` 这类兼容入口。写入路径以 `import_graph_data_tool(mode="ingest")` 为主，并通过 MCP 本地链路完成校验、dry-run、plan_hash、confirm 和执行。

如果 V1 上线版本需要支持删除，不能重新开放宽泛的 `manage_graph_data_tool(mode="delete")`，也不能要求用户直接执行 `.drop()` Gremlin。删除能力应作为独立、受控、可审计的高风险工具暴露。

## 2. 设计原则

1. 删除是高风险操作，默认必须比写入更保守。
2. 用户只看到明确的删除工具，不看到内部兼容工具。
3. 所有删除必须经过 `dry_run -> plan_hash -> confirm -> execute`。
4. confirm 阶段必须重新读取配置、schema 和目标对象，防止 dry-run 后图状态变化。
5. 删除匹配必须唯一：`matched_count == 1` 才允许执行。
6. 第一版不支持条件批量删除。
7. 第一版不支持级联删除。有关联边的顶点删除应被拒绝。
8. 普通删除路径不使用 `execute_gremlin_write_tool`。
9. 删除后必须反查确认目标已经不存在。
10. 部分成功后失败必须返回 `partial`，并包含已删除数量、失败明细和补偿建议。

## 3. 用户可见工具

新增一个稳定工具：

```python
delete_graph_data_tool(
    change_plan: dict,
    dry_run: bool = True,
    confirm: bool = False,
    plan_hash: str | None = None,
    nonce: str | None = None,
    expires_at: float | None = None,
) -> dict
```

该工具内部可以复用现有 `manage_graph_data(mode="delete")` 实现，但 `manage_graph_data_tool` 不重新暴露为 MCP 用户工具。

## 4. 支持范围

V1.1 只支持两类删除：

| 操作 | 是否支持 | 说明 |
| --- | --- | --- |
| `delete_vertex` | 支持 | 必须通过 label + primary key match 精确匹配一个顶点 |
| `delete_edge` | 支持 | 必须通过 edge label + source/target 精确匹配一条边 |
| 条件批量删除 | 不支持 | 防止误删多条数据 |
| `cascade=true` 顶点删除 | 不支持 | 只做预览并返回拒绝 |
| SQL delete | 不支持 | SQL 能力不属于 V1 稳定路径 |
| 自然语言删除 | 不支持 | 可后续设计为先生成 change_plan，再必须人工确认 |
| 直接 Gremlin drop | 不支持 | 普通用户路径必须走受控删除工具 |

## 5. 输入契约

### 5.1 删除顶点

```json
{
  "operations": [
    {
      "op": "delete_vertex",
      "label": "person",
      "match": {
        "name": "Alice"
      },
      "cascade": false
    }
  ]
}
```

要求：

- `label` 必须存在于 live schema。
- `match` 必须包含该 vertex label 的全部 primary keys。
- `match` 字段只能使用该 label 已定义属性。
- `cascade` 默认 `false`。
- 如果目标顶点有关联边，返回 `BLOCKED_BY_RELATIONSHIPS`。

### 5.2 删除边

```json
{
  "operations": [
    {
      "op": "delete_edge",
      "label": "knows",
      "source_label": "person",
      "source_match": {
        "name": "Alice"
      },
      "target_label": "person",
      "target_match": {
        "name": "Bob"
      }
    }
  ]
}
```

要求：

- `label` 必须存在于 edge label schema。
- `source_label` 和 `target_label` 必须与 edge schema 定义一致。
- `source_match` 和 `target_match` 必须包含对应顶点 label 的全部 primary keys。
- source 顶点必须唯一匹配。
- target 顶点必须唯一匹配。
- edge 本身必须唯一匹配。

## 6. dry-run 输出

dry-run 不执行删除，只返回影响预览和确认材料。

示例：

```json
{
  "ok": true,
  "data": {
    "status": "dry_run",
    "mutation_summary": {
      "delete_vertex": 1,
      "delete_edge": 0
    },
    "items": [
      {
        "operation_index": 0,
        "op": "delete_vertex",
        "label": "person",
        "matched_count": 1,
        "associated_edge_count": 0
      }
    ],
    "plan_hash": "sha256:...",
    "plan_context": {
      "nonce": "...",
      "expires_at": 1790000000
    }
  },
  "warnings": [],
  "next_actions": [
    "Review matched_count and operation details.",
    "Run delete_graph_data_tool with dry_run=false, confirm=true, plan_hash, nonce, and expires_at."
  ],
  "meta": {
    "tool": "delete_graph_data_tool",
    "readonly": false
  }
}
```

## 7. confirm 规则

confirm 阶段必须重验以下内容：

1. `readonly` 仍为 `false`。
2. `plan_hash` 存在且匹配。
3. `nonce` 存在且匹配 dry-run context。
4. `expires_at` 未过期。
5. 当前 graph url、graph name、graphspace、principal 与 dry-run 时一致。
6. 当前 live schema hash 与 dry-run 时一致。
7. 当前 normalized payload digest 与 dry-run 时一致。
8. 每个删除目标重新匹配后仍满足 `matched_count == 1`。
9. 顶点删除时仍没有关联边，除非未来显式支持 cascade。

只要任一条件不满足，必须拒绝执行，并要求重新 dry-run。

## 8. 执行规则

执行阶段按 operation 顺序逐条删除：

1. 执行前再次读取 matched count。
2. matched count 不等于 1，立即停止。
3. 删除顶点前检查 `bothE().count()`。
4. 删除边前检查 source、target、edge 三者唯一。
5. 执行 MCP 内部生成的受控 Gremlin，不接受用户传入 Gremlin。
6. 删除后立即反查。
7. 反查仍存在则返回 error/degraded。
8. 如果前序操作已经成功，后续失败，返回 `partial`。

## 9. 返回状态

| 状态 | 含义 |
| --- | --- |
| `dry_run` | 只预览，不写入 |
| `success` | 所有删除均成功，并且反查确认不存在 |
| `partial` | 部分操作已成功，后续失败 |
| `degraded` | 删除接口返回成功，但验证或结果归一存在异常 |
| `error` | 未执行任何删除或执行前失败 |

`partial` 必须包含：

- `deleted_count`
- `executed_items`
- `failed_items`
- `failure_operation_index`
- `compensation_suggestions`

## 10. 错误类型建议

| 错误类型 | 触发场景 |
| --- | --- |
| `READONLY_VIOLATION` | readonly 模式下尝试删除 |
| `CONFIRM_REQUIRED` | 非 dry-run 但未 confirm |
| `PLAN_HASH_REQUIRED` | confirm 缺少 plan_hash |
| `PLAN_HASH_MISMATCH` | plan_hash 重验失败 |
| `PLAN_EXPIRED` | expires_at 过期 |
| `INVALID_GRAPH_DATA` | change_plan 格式、schema、字段校验失败 |
| `MATCH_NOT_FOUND` | matched_count 为 0 |
| `MATCH_NOT_UNIQUE` | matched_count 大于 1 |
| `BLOCKED_BY_RELATIONSHIPS` | 顶点存在关联边 |
| `CASCADE_NOT_ENABLED` | 用户请求 cascade=true |
| `DELETE_VERIFY_FAILED` | 删除后反查目标仍存在 |
| `PARTIAL_WRITE` | 部分删除后失败 |

## 11. 实施计划

### M8-1 公开删除工具

任务：

- 在 `server.py` 新增 `delete_graph_data_tool`。
- 工具只接受 `change_plan`，不接受裸 Gremlin。
- 内部调用 `manage_graph_data(mode="delete")`。
- 设置 `plan_tool_name="delete_graph_data_tool"`，确保 plan_hash 绑定到用户可见工具名。
- 不恢复 `manage_graph_data_tool` 用户入口。

预计工程量：0.5 人天。

### M8-2 收紧删除契约

任务：

- 确认 `mode="delete"` 只允许 `delete_vertex` 和 `delete_edge`。
- 确认每个操作必须唯一匹配。
- 确认顶点删除默认 `cascade=false`。
- 确认 `cascade=true` 只预览关联边，不执行。
- 确认 readonly runtime guard 覆盖删除执行路径。

预计工程量：0.5 到 1 人天。

### M8-3 dry-run 预览增强

任务：

- dry-run 返回每个 operation 的 `matched_count`。
- 删除边时返回 `source_matched_count`、`target_matched_count`、`matched_count`。
- 删除顶点时返回 `associated_edge_count`。
- 返回 `mutation_summary`、`plan_hash`、`nonce`、`expires_at`。
- next_actions 指导用户如何 confirm。

预计工程量：0.5 人天。

### M8-4 执行后验证

任务：

- 删除顶点后反查顶点 matched count，应为 0。
- 删除边后反查边 matched count，应为 0。
- 验证失败时返回 `DELETE_VERIFY_FAILED`。
- 部分删除后失败时返回 `partial`。
- partial 中包含已执行结果和补偿建议。

预计工程量：0.5 到 1 人天。

### M8-5 测试

必须新增或补齐以下测试：

- `readonly=true` 删除被拒绝。
- `dry_run=true` 不执行删除。
- `dry_run=false` 且 `confirm=false` 被拒绝。
- confirm 缺少 `plan_hash` 被拒绝。
- `plan_hash` 错误被拒绝。
- `expires_at` 过期被拒绝。
- dry-run 后 schema 或目标图变化，confirm 被拒绝。
- 顶点匹配 0 个被拒绝。
- 顶点匹配多个被拒绝。
- 删除有关联边的顶点被拒绝。
- `cascade=true` 被拒绝。
- 删除边时 source 匹配 0 个被拒绝。
- 删除边时 target 匹配多个被拒绝。
- 删除边成功后反查为 0。
- 删除顶点成功后反查为 0。
- 部分成功后失败返回 `partial`。
- `execute_gremlin_read_tool("g.V().drop()")` 仍拒绝。
- `execute_gremlin_write_tool` 仍 admin-only。

预计工程量：1 到 1.5 人天。

### M8-6 文档

任务：

- README 增加受控删除章节。
- README.zh-CN 增加中文示例。
- 明确说明不支持批量删除和 cascade。
- 明确说明普通用户不要使用写 Gremlin 删除。
- 给出 dry-run 和 confirm 示例。

预计工程量：0.5 人天。

## 12. 工程量估计

| 范围 | 估计 |
| --- | --- |
| 受控删除 MVP | 2.5 到 4 人天 |
| 加完整真实 HugeGraph 集成验证 | 4 到 5 人天 |
| 支持批量删除、cascade、备份/恢复、审计 | 1.5 到 2 周以上 |

## 13. 推荐上线范围

第一版上线如必须支持删除，推荐只上线以下能力：

- `delete_graph_data_tool`
- 精确删除顶点
- 精确删除边
- dry-run / plan_hash / confirm
- matched count 必须等于 1
- 禁止 cascade
- 禁止批量条件删除
- 删除后反查
- partial/error/degraded 结构化返回

不建议第一版上线：

- 自然语言直接删除
- SQL delete
- 批量条件删除
- cascade 删除
- 用户自定义 `.drop()` Gremlin
- update/delete 统一大工具

## 14. 风险与后续版本

后续版本可以考虑：

- 受控批量删除，但必须增加最大数量限制和额外确认文本。
- cascade 删除，但必须先输出完整关联边清单。
- 删除前自动备份目标点边快照。
- 删除审计日志。
- 删除恢复工具。
- 自然语言删除计划生成，但仍必须人工 review change_plan。

这些能力不建议进入第一版上线范围。
