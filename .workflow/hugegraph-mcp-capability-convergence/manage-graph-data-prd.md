# PRD: HugeGraph MCP 管理图数据能力

日期：2026-05-26

关联计划：[manage-graph-data-improvement-plan.md](./manage-graph-data-improvement-plan.md)

## 1. 介绍

当前 HugeGraph MCP 已经提供查看图状态、查询图、管理 schema 和导入图数据四类主功能。其中“导入图数据”已经支持自然语言抽取、结构化 graph payload、表格 rows + mapping，并通过 dry-run、plan_hash、confirm 实现受控新增写入。

但是，删除和更新图数据目前主要依赖 `execute_gremlin_write_tool` 这类底层调试能力。该能力虽然可以完成删除和更新，但要求用户直接编写 Gremlin，缺少统一校验、影响预览、dry-run、plan_hash、confirm 和执行后验证，不适合作为普通用户主路径。

本 PRD 定义“管理图数据”能力，将现有“导入图数据”升级为覆盖新增、更新、删除的统一高层能力。系统应让用户通过结构化变更计划表达图数据变更，由 MCP 负责校验、预览、确认和执行。底层 Gremlin 写操作应作为内部执行机制或管理员调试能力，不作为普通用户主入口。

本阶段不要求实现复杂自然语言删除/更新、不要求自动消歧、不要求批量回滚和完整审计系统。GraphRAG 自然语言问图继续作为高级/实验能力，不纳入本 PRD 主路径。

## 2. 目标

### 2.1 产品目标

- 将“导入图数据”升级为“管理图数据”。
- 支持图数据新增、更新、删除的统一用户入口。
- 所有图数据写操作都经过 validate、dry-run、plan_hash、confirm、execute、verify。
- 降低普通用户直接使用 `execute_gremlin_write_tool` 的需求。
- 保留现有导入能力，并保持兼容。

### 2.2 非目标

- 不实现任意自然语言删除/更新的默认主路径。
- 不实现多候选实体自动消歧。
- 不实现完整权限系统。
- 不实现批量回滚。
- 不实现完整操作历史审计。
- 不将 GraphRAG 问图作为主查询路径。

## 3. 用户和场景

### 3.1 目标用户

- 使用 Agent 操作 HugeGraph 的业务用户。
- 维护知识图谱数据的开发者。
- 需要安全写入、更新、删除图数据的管理员或测试者。

### 3.2 典型场景

- 从自然语言中抽取实体和关系，并导入图数据库。
- 从表格 rows + mapping 中生成点边并导入。
- 删除 Alice 和 Bob 之间的 colleague 关系，但保留 Alice 和 Bob 顶点。
- 更新 Alice 的 occupation 属性。
- 删除某个孤立测试顶点。
- 在执行真实写入前查看影响预览。

## 4. 需求列表

### 4.1 用户入口升级

- **用户故事**: 作为一名 **Agent 用户**, 我希望 **使用一个统一入口管理图数据**, 以便 **不用区分导入、更新、删除背后的底层 Gremlin 执行方式**。
- **验收标准 (EARS 格式)**:
  - **MGD-U1**: The **HugeGraph MCP** shall **提供 `manage_graph_data_tool` 作为图数据新增、更新、删除的主入口**。
  - **MGD-U2**: The **HugeGraph MCP** shall **保留 `import_graph_data_tool` 作为兼容入口，并将其内部路由到管理图数据流程或复用同一套校验和写入机制**。
  - **MGD-U3**: The **HugeGraph MCP** shall **在普通用户文档中优先介绍“管理图数据”，而不是优先介绍直接 Gremlin 写入调试入口**。
  - **MGD-X1**: IF **普通用户尝试用底层写 Gremlin 完成常规删除或更新**, THEN the **HugeGraph MCP** shall **提示该入口属于调试/管理员能力，并建议使用管理图数据流程**。

### 4.2 统一变更计划

- **用户故事**: 作为一名 **开发者或 Agent 用户**, 我希望 **用结构化变更计划描述新增、更新、删除**, 以便 **系统可以在执行前校验和预览影响**。
- **验收标准 (EARS 格式)**:
  - **MGD-E1**: WHEN **用户提交图数据变更**, the **HugeGraph MCP** shall **接受 `graph_change_plan` 格式作为统一中间格式**。
  - **MGD-E2**: WHEN **现有 `graph_data` 被提交导入**, the **HugeGraph MCP** shall **将 vertices 和 edges 转换为 `create_vertex` 和 `create_edge` 操作**。
  - **MGD-E3**: WHEN **用户提交 update 或 delete 请求**, the **HugeGraph MCP** shall **要求使用 `change_plan.operations` 描述精确操作**。
  - **MGD-X2**: IF **operation 不是对象或缺少 `op` 字段**, THEN the **HugeGraph MCP** shall **拒绝执行并返回结构化校验错误**。
  - **MGD-X3**: IF **`op` 不在允许列表中**, THEN the **HugeGraph MCP** shall **拒绝执行并列出允许的操作类型**。

允许的 `op` 初始集合：

```text
create_vertex
create_edge
update_vertex
update_edge
delete_vertex
delete_edge
```

### 4.3 新增和导入图数据

- **用户故事**: 作为一名 **知识图谱构建用户**, 我希望 **继续从自然语言、结构化 payload 或表格数据导入图数据**, 以便 **不破坏现有导入工作流**。
- **验收标准 (EARS 格式)**:
  - **MGD-E4**: WHEN **用户提交自然语言文本并请求抽图**, the **HugeGraph MCP** shall **返回候选 `graph_data`，且默认不写入图数据库**。
  - **MGD-E5**: WHEN **用户请求导入结构化 `graph_data`**, the **HugeGraph MCP** shall **将其转换为 create operations 并进入统一 dry-run 流程**。
  - **MGD-E6**: WHEN **用户请求导入表格 rows + mapping**, the **HugeGraph MCP** shall **先生成 `graph_data` 或 create operations，再进入统一 dry-run 流程**。
  - **MGD-E7**: WHEN **导入 dry-run 成功**, the **HugeGraph MCP** shall **返回预计新增顶点数、预计新增边数、warnings 和 plan_hash**。
  - **MGD-X4**: IF **导入 payload 缺少 live schema 要求的顶点主键**, THEN the **HugeGraph MCP** shall **拒绝导入并指出缺失的 label 和主键字段**。
  - **MGD-X5**: IF **边的 source 或 target 无法解析**, THEN the **HugeGraph MCP** shall **拒绝导入并指出无法解析的端点**。

### 4.4 删除边

- **用户故事**: 作为一名 **图数据维护用户**, 我希望 **删除两个实体之间的指定关系但保留实体本身**, 以便 **修正错误关系而不误删顶点**。
- **验收标准 (EARS 格式)**:
  - **MGD-E8**: WHEN **用户提交 `delete_edge` 操作**, the **HugeGraph MCP** shall **根据 label、source_label、source、target_label、target 定位候选边**。
  - **MGD-E9**: WHEN **`delete_edge` dry-run 成功**, the **HugeGraph MCP** shall **返回将删除的边、matched_count、source 顶点和 target 顶点，并说明不会删除端点顶点**。
  - **MGD-E10**: WHEN **用户确认执行 `delete_edge` 且 plan_hash 匹配**, the **HugeGraph MCP** shall **仅删除匹配到的边，不删除 source 或 target 顶点**。
  - **MGD-X6**: IF **source 顶点无法定位**, THEN the **HugeGraph MCP** shall **拒绝删除并返回 SOURCE_NOT_FOUND 或等价错误**。
  - **MGD-X7**: IF **target 顶点无法定位**, THEN the **HugeGraph MCP** shall **拒绝删除并返回 TARGET_NOT_FOUND 或等价错误**。
  - **MGD-X8**: IF **matched_count 为 0**, THEN the **HugeGraph MCP** shall **拒绝执行并说明没有可删除的边**。
  - **MGD-X9**: IF **matched_count 大于 1 且 allow_multiple 未启用**, THEN the **HugeGraph MCP** shall **拒绝执行并要求用户进一步限定匹配条件**。

示例输入：

```json
{
  "operations": [
    {
      "op": "delete_edge",
      "label": "colleague",
      "source_label": "person",
      "source": {
        "name": "Alice"
      },
      "target_label": "person",
      "target": {
        "name": "Bob"
      }
    }
  ]
}
```

### 4.5 删除顶点

- **用户故事**: 作为一名 **图数据维护用户**, 我希望 **删除一个明确匹配的顶点**, 以便 **清理错误或测试数据**。
- **验收标准 (EARS 格式)**:
  - **MGD-E11**: WHEN **用户提交 `delete_vertex` 操作**, the **HugeGraph MCP** shall **根据 label 和 match 定位候选顶点**。
  - **MGD-E12**: WHEN **`delete_vertex` dry-run 成功**, the **HugeGraph MCP** shall **返回将删除的顶点数量、顶点摘要和关联边影响**。
  - **MGD-U4**: The **HugeGraph MCP** shall **默认使用 `cascade=false`**。
  - **MGD-X10**: IF **`cascade=false` 且目标顶点存在关联边**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 BLOCKED_BY_RELATIONSHIPS 或等价错误**。
  - **MGD-E13**: WHEN **`cascade=true` 被显式启用**, the **HugeGraph MCP** shall **在 dry-run 中列出将被级联删除的关联边**。
  - **MGD-X11**: IF **目标顶点匹配多个对象且 allow_multiple 未启用**, THEN the **HugeGraph MCP** shall **拒绝执行并要求用户进一步限定匹配条件**。

### 4.6 更新顶点

- **用户故事**: 作为一名 **图数据维护用户**, 我希望 **更新指定顶点的非主键属性**, 以便 **修正或补全实体信息**。
- **验收标准 (EARS 格式)**:
  - **MGD-E14**: WHEN **用户提交 `update_vertex` 操作**, the **HugeGraph MCP** shall **根据 label 和 match 定位目标顶点**。
  - **MGD-E15**: WHEN **`update_vertex` dry-run 成功**, the **HugeGraph MCP** shall **返回目标顶点、matched_count 和将设置的属性**。
  - **MGD-E16**: WHEN **用户确认执行 `update_vertex` 且 plan_hash 匹配**, the **HugeGraph MCP** shall **更新目标顶点属性并返回更新摘要**。
  - **MGD-X12**: IF **set 为空**, THEN the **HugeGraph MCP** shall **拒绝执行并返回校验错误**。
  - **MGD-X13**: IF **set 包含 vertex label 的 primary key 字段**, THEN the **HugeGraph MCP** shall **拒绝执行并说明不允许更新主键**。
  - **MGD-X14**: IF **set 包含 schema 中不存在的属性**, THEN the **HugeGraph MCP** shall **拒绝执行并指出非法属性**。
  - **MGD-X15**: IF **match 未包含该 vertex label 的 primary_keys**, THEN the **HugeGraph MCP** shall **拒绝执行并要求提供完整主键**。

示例输入：

```json
{
  "operations": [
    {
      "op": "update_vertex",
      "label": "person",
      "match": {
        "name": "Alice"
      },
      "set": {
        "occupation": "工程师"
      }
    }
  ]
}
```

### 4.7 更新边

- **用户故事**: 作为一名 **图数据维护用户**, 我希望 **更新指定关系的属性**, 以便 **修正关系上的时间、权重或状态信息**。
- **验收标准 (EARS 格式)**:
  - **MGD-E17**: WHEN **用户提交 `update_edge` 操作**, the **HugeGraph MCP** shall **根据 label、source、target 定位目标边**。
  - **MGD-E18**: WHEN **`update_edge` dry-run 成功**, the **HugeGraph MCP** shall **返回目标边、matched_count 和将设置的属性**。
  - **MGD-E19**: WHEN **用户确认执行 `update_edge` 且 plan_hash 匹配**, the **HugeGraph MCP** shall **更新目标边属性并返回更新摘要**。
  - **MGD-X16**: IF **set 包含 edge label schema 中不存在的属性**, THEN the **HugeGraph MCP** shall **拒绝执行并指出非法属性**。
  - **MGD-X17**: IF **matched_count 不等于 1 且 allow_multiple 未启用**, THEN the **HugeGraph MCP** shall **拒绝执行并要求用户进一步限定匹配条件**。

### 4.8 dry-run、plan_hash 和 confirm

- **用户故事**: 作为一名 **系统管理员或业务用户**, 我希望 **所有写操作执行前都能预览并确认**, 以便 **避免误写、误删或误改图数据**。
- **验收标准 (EARS 格式)**:
  - **MGD-E20**: WHEN **用户请求 dry-run 图数据变更**, the **HugeGraph MCP** shall **只执行校验和影响预览，不修改图数据库**。
  - **MGD-E21**: WHEN **dry-run 成功**, the **HugeGraph MCP** shall **返回 plan_hash、mutation_summary、preview 和 warnings**。
  - **MGD-E22**: WHEN **用户请求真实执行图数据变更**, the **HugeGraph MCP** shall **要求 dry_run=false、confirm=true 和匹配的 plan_hash**。
  - **MGD-X18**: IF **confirm 缺失或为 false**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 CONFIRM_REQUIRED**。
  - **MGD-X19**: IF **plan_hash 缺失或不匹配**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 PLAN_HASH_MISMATCH**。
  - **MGD-E23**: WHEN **confirm 执行时**, the **HugeGraph MCP** shall **基于提交的 change_plan、graph、graphspace、操作顺序和当前 schema 上下文重新计算 plan_hash**。
  - **MGD-X20**: IF **dry-run 后 payload、目标图、schema 上下文或操作顺序发生变化**, THEN the **HugeGraph MCP** shall **拒绝执行并要求重新 dry-run**。

### 4.9 readonly 和 guard

- **用户故事**: 作为一名 **系统管理员**, 我希望 **readonly 模式下所有图数据写操作都被拒绝**, 以便 **安全连接生产图或只读环境**。
- **验收标准 (EARS 格式)**:
  - **MGD-S1**: WHILE **HUGEGRAPH_MCP_READONLY=true**, the **HugeGraph MCP** shall **允许 validate 和 dry-run，但拒绝所有真实图数据写入**。
  - **MGD-S2**: WHILE **执行 create、update 或 delete 操作**, the **HugeGraph MCP** shall **在发送写请求前执行运行时 guard**。
  - **MGD-X21**: IF **底层 `execute_gremlin_write_tool` 被直接调用**, THEN the **HugeGraph MCP** shall **仍然执行 readonly guard，而不是仅依赖工具是否隐藏**。

### 4.10 执行后验证

- **用户故事**: 作为一名 **Agent 用户**, 我希望 **写入、删除或更新后能看到可验证结果**, 以便 **确认操作确实生效**。
- **验收标准 (EARS 格式)**:
  - **MGD-E24**: WHEN **create/import 执行成功**, the **HugeGraph MCP** shall **返回 batch_id、写入顶点数、写入边数和可选验证建议**。
  - **MGD-E25**: WHEN **delete_edge 执行成功**, the **HugeGraph MCP** shall **验证目标边不再存在，并返回 source 和 target 顶点仍存在的状态**。
  - **MGD-E26**: WHEN **update_vertex 或 update_edge 执行成功**, the **HugeGraph MCP** shall **返回更新后的关键属性或验证查询摘要**。
  - **MGD-X22**: IF **执行后验证失败**, THEN the **HugeGraph MCP** shall **返回 VERIFY_FAILED 或等价 warning，并包含底层执行结果**。

## 5. 数据结构

### 5.1 graph_change_plan

```json
{
  "operations": [
    {
      "op": "delete_edge",
      "label": "colleague",
      "source_label": "person",
      "source": {
        "name": "Alice"
      },
      "target_label": "person",
      "target": {
        "name": "Bob"
      }
    }
  ]
}
```

### 5.2 dry-run 输出

```json
{
  "ok": true,
  "data": {
    "valid": true,
    "plan_hash": "71f7051e85b6cd43",
    "mutation_summary": {
      "create_vertices": 0,
      "create_edges": 0,
      "update_vertices": 0,
      "update_edges": 0,
      "delete_vertices": 0,
      "delete_edges": 1
    },
    "preview": {
      "delete_edges": [
        {
          "label": "colleague",
          "source": {
            "name": "Alice"
          },
          "target": {
            "name": "Bob"
          },
          "matched_count": 1
        }
      ],
      "unchanged_vertices": [
        {
          "label": "person",
          "match": {
            "name": "Alice"
          }
        },
        {
          "label": "person",
          "match": {
            "name": "Bob"
          }
        }
      ]
    },
    "warnings": []
  }
}
```

### 5.3 confirm 输出

```json
{
  "ok": true,
  "data": {
    "batch_id": "batch-...",
    "mutation_summary": {
      "delete_edges": 1
    },
    "verification": {
      "deleted_edge_exists": false,
      "source_vertex_exists": true,
      "target_vertex_exists": true
    }
  }
}
```

## 6. 执行和安全设计

### 6.1 模块

新增：

```text
hugegraph_mcp/tools/manage_graph_data.py
```

核心函数：

```python
manage_graph_data(...)
validate_graph_change_plan(...)
dry_run_graph_change_plan(...)
execute_graph_change_plan(...)
calculate_graph_change_plan_hash(...)
verify_graph_change_result(...)
```

复用：

```text
extract_graph_data.py
import_table.py
ingest_graph_data.py
gremlin_tools.py
schema_tools.py
envelope.py
guard.py
```

### 6.2 受控 Gremlin 模板

删除边：

```text
g.V().hasLabel(source_label).has(pk, value)
 .outE(label)
 .where(inV().hasLabel(target_label).has(pk, value))
 .drop()
```

更新顶点：

```text
g.V().hasLabel(label).has(pk, value)
 .property(prop, value)
```

更新边：

```text
g.V().hasLabel(source_label).has(pk, value)
 .outE(label)
 .where(inV().hasLabel(target_label).has(pk, value))
 .property(prop, value)
```

删除顶点：

```text
g.V().hasLabel(label).has(pk, value).drop()
```

执行前必须先使用只读查询确认 `matched_count` 和影响范围。

## 7. 测试计划

新增测试：

```text
hugegraph-mcp/tests/test_manage_graph_data.py
```

覆盖：

- graph_data 转 create operations。
- table rows + mapping 进入统一 dry-run。
- delete_edge dry-run 成功。
- delete_edge source 不存在。
- delete_edge target 不存在。
- delete_edge matched_count=0。
- delete_edge matched_count>1 且 allow_multiple=false。
- delete_vertex cascade=false 且有关联边时拒绝。
- update_vertex 成功。
- update_vertex 更新主键拒绝。
- update_vertex 字段不存在拒绝。
- update_edge 成功。
- update_edge 字段不存在拒绝。
- dry-run 返回 plan_hash。
- confirm=false 返回 CONFIRM_REQUIRED。
- plan_hash mismatch 返回 PLAN_HASH_MISMATCH。
- readonly 模式拒绝真实执行。

实际测试：

```text
1. 创建 AliceTest 和 BobTest colleague。
2. dry-run 删除 AliceTest -> BobTest colleague。
3. confirm 删除。
4. 验证边不存在，AliceTest 和 BobTest 顶点仍存在。
5. dry-run 更新 AliceTest occupation。
6. confirm 更新。
7. 验证属性变更。
```

## 8. 里程碑

### M1: 入口和数据结构

- 新增 `manage_graph_data_tool`。
- 定义 `graph_change_plan`。
- 保留 `import_graph_data_tool` 兼容入口。

### M2: 安全链路

- 实现 validate。
- 实现 dry-run。
- 实现 plan_hash。
- 实现 confirm 校验。

### M3: 删除和更新

- 实现 `delete_edge`。
- 实现 `update_vertex`。
- 实现 `update_edge`。
- 实现 `delete_vertex`，默认 `cascade=false`。

### M4: 验证和文档

- 实现执行后验证。
- 补齐测试。
- 更新 README 和用户文档。
- 完成真实回归测试。

## 9. 验收样例

### 9.1 删除关系

用户请求：

```text
删除 Alice 和 Bob 的 colleague 关系
```

dry-run 应返回：

```text
将删除 1 条边：
Alice -[colleague {date: 2026-05-26}]-> Bob

不会删除：
Alice 顶点
Bob 顶点

plan_hash: ...
```

confirm 后应返回：

```text
删除成功
Alice 和 Bob 仍存在
colleague 关系不存在
```

### 9.2 更新属性

用户请求：

```text
把 Alice 的 occupation 改为 工程师
```

dry-run 应返回：

```text
将更新 1 个 person 顶点：
Alice.occupation = 工程师

plan_hash: ...
```

confirm 后应返回：

```text
更新成功
查询 Alice 可看到 occupation=工程师
```

## 10. 风险

- 删除能力必须默认保守，尤其是 `delete_vertex`。
- `cascade=true` 不应在第一批默认开放。
- 更新主键字段必须拒绝。
- 删除或更新匹配多个对象时默认拒绝。
- `execute_gremlin_write_tool` 仍应作为调试入口，不应成为普通用户路径。
- GraphRAG 问图当前不稳定，不应阻塞本 PRD。
