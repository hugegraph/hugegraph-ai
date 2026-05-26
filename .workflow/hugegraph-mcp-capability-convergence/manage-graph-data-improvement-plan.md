# 管理图数据能力改进计划

日期：2026-05-26

## 1. 背景

当前 MCP 已经把主要用户能力收敛为：

- 查看图状态和 schema
- 查询图
- 设计和管理 schema
- 导入图数据

其中“导入图数据”主要覆盖新增/导入场景，包括自然语言抽取、结构化 graph payload、表格 rows + mapping，再通过 dry-run、plan_hash、confirm 执行受控写入。

但删除和更新图数据目前主要依赖 `execute_gremlin_write_tool` 这类底层调试能力。它可以完成删除/更新，但要求用户直接写 Gremlin，缺少 dry-run、影响预览、plan_hash、confirm、安全校验和执行后验证，不适合作为普通用户主功能。

因此，本计划建议将“导入图数据”升级为更通用的“管理图数据”能力，把新增、更新、删除纳入同一条安全链路。

## 2. 目标

新增高层能力：

```text
管理图数据
```

支持：

- create / import
- update
- delete
- dry-run
- plan_hash
- confirm
- 执行后验证

目标不是让用户直接执行任意写 Gremlin，而是让用户提交结构化变更计划，由 MCP 校验、预览、确认后生成受控写操作。

## 3. 能力边界

本阶段支持：

- 结构化 graph payload 导入
- 自然语言抽取后导入
- 表格 rows + mapping 导入
- 删除指定顶点
- 删除指定边
- 更新顶点属性
- 更新边属性

本阶段暂不支持：

- 复杂自然语言删除
- 复杂自然语言更新
- 多候选实体自动消歧
- 批量回滚
- 权限系统
- 完整操作历史审计
- GraphRAG 主路径改造

GraphRAG 继续保留为高级/实验能力，不纳入本计划主路径。

## 4. 入口设计

新增主入口：

```text
manage_graph_data_tool
```

建议参数：

```text
mode: "extract" | "import" | "table" | "update" | "delete"
text: str | null
graph_data: dict | null
table_data: dict | null
mapping: dict | null
change_plan: dict | null
dry_run: bool = true
confirm: bool = false
plan_hash: str | null
```

兼容策略：

```text
import_graph_data_tool 保留为兼容入口
内部转发到 manage_graph_data_tool
文档主推 manage_graph_data_tool
```

推荐最终工具面：

```text
inspect_graph_tool
query_graph_tool
manage_schema_tool
manage_graph_data_tool
refresh_vid_embeddings_tool
execute_gremlin_write_tool
```

其中：

```text
execute_gremlin_write_tool 仍为 debug/admin 能力，不进入普通用户主路径。
```

## 5. 统一变更计划格式

新增中间格式：

```text
graph_change_plan
```

示例：

```json
{
  "operations": [
    {
      "op": "create_vertex",
      "label": "person",
      "properties": {
        "name": "Alice"
      }
    },
    {
      "op": "create_edge",
      "label": "colleague",
      "source_label": "person",
      "source": {
        "name": "Alice"
      },
      "target_label": "person",
      "target": {
        "name": "Bob"
      },
      "properties": {
        "date": "2026-05-26"
      }
    },
    {
      "op": "update_vertex",
      "label": "person",
      "match": {
        "name": "Alice"
      },
      "set": {
        "occupation": "工程师"
      }
    },
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

现有 `graph_data` 可转换为：

```text
create_vertex
create_edge
```

删除和更新优先只接受 `change_plan`。

## 6. 安全链路

所有写操作统一走：

```text
validate
-> dry-run
-> plan_hash
-> confirm
-> execute
-> verify
```

规则：

```text
dry_run=true:
  只校验和预览，不写入。

dry_run=false + confirm=false:
  返回 CONFIRM_REQUIRED。

dry_run=false + confirm=true + plan_hash mismatch:
  返回 PLAN_HASH_MISMATCH。

dry_run=false + confirm=true + plan_hash match:
  执行写入。
```

`plan_hash` 绑定：

```text
graphspace
graph
operation list
当前 schema 摘要
```

## 7. 删除能力设计

### 7.1 删除边

输入：

```json
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
```

dry-run 返回：

```json
{
  "valid": true,
  "plan_hash": "...",
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
    "delete_vertices": [],
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
  }
}
```

执行要求：

```text
source 必须能定位到顶点
target 必须能定位到顶点
matched_count 必须为 1
不会删除 source / target 顶点
```

### 7.2 删除顶点

输入：

```json
{
  "op": "delete_vertex",
  "label": "person",
  "match": {
    "name": "Alice"
  },
  "cascade": false
}
```

规则：

```text
cascade=false:
  如果顶点存在关联边，dry-run 返回 BLOCKED_BY_RELATIONSHIPS。

cascade=true:
  dry-run 必须列出将被删除的关联边。
```

本阶段默认：

```text
cascade=false
```

## 8. 更新能力设计

### 8.1 更新顶点

输入：

```json
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
```

dry-run 返回：

```json
{
  "preview": {
    "update_vertices": [
      {
        "label": "person",
        "match": {
          "name": "Alice"
        },
        "matched_count": 1,
        "set": {
          "occupation": "工程师"
        }
      }
    ]
  }
}
```

### 8.2 更新边

输入：

```json
{
  "op": "update_edge",
  "label": "colleague",
  "source_label": "person",
  "source": {
    "name": "Alice"
  },
  "target_label": "person",
  "target": {
    "name": "Bob"
  },
  "set": {
    "date": "2026-05-27"
  }
}
```

更新限制：

```text
不允许更新主键字段
不允许更新 schema 中不存在的属性
不允许 match 到多个对象时直接执行，除非 allow_multiple=true
```

本阶段默认：

```text
allow_multiple=false
```

## 9. 校验规则

通用校验：

```text
operation 必须是对象
op 必须在白名单内
label 必须存在于 live schema
属性必须存在于 live schema
顶点 match 必须包含该 vertex label 的 primary_keys
边 source / target 必须能定位到顶点
```

删除校验：

```text
delete_edge:
  source / target 均必须能解析
  matched_count 必须为 1 才允许 confirm 执行

delete_vertex:
  match 必须能定位到 1 个顶点
  cascade=false 时若有关联边则拒绝执行
```

更新校验：

```text
update_vertex:
  match 必须定位到 1 个顶点
  set 不能为空
  set 不允许包含 primary key
  set 字段必须属于 vertex label properties

update_edge:
  source / target 必须定位
  edge matched_count 必须为 1
  set 字段必须属于 edge label properties
```

## 10. 执行层设计

新增模块：

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
```

复用现有模块：

```text
extract_graph_data.py
import_table.py
ingest_graph_data.py
gremlin_tools.py
schema_tools.py
envelope.py
guard.py
```

原则：

```text
不要让普通用户直接传任意写 Gremlin。
执行层内部生成受控 Gremlin 模板。
```

## 11. 受控 Gremlin 模板

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

执行前必须先用只读查询确认 `matched_count`。

## 12. 测试计划

新增测试文件：

```text
test_manage_graph_data.py
```

单元测试覆盖：

```text
create graph_data 转 change_plan
delete_edge dry-run 成功
delete_edge source 不存在
delete_edge target 不存在
delete_edge matched_count=0
delete_edge matched_count>1 拒绝
delete_vertex cascade=false 有关联边拒绝
update_vertex 成功
update_vertex 更新主键拒绝
update_vertex 字段不存在拒绝
update_edge 成功
update_edge 字段不存在拒绝
dry-run 返回 plan_hash
confirm=false 拒绝
plan_hash mismatch 拒绝
readonly 模式拒绝执行
```

集成/实际测试：

```text
创建 AliceTest 和 BobTest colleague
dry-run 删除 AliceTest -> BobTest colleague
confirm 删除
验证边不存在，顶点仍存在

dry-run 更新 AliceTest occupation
confirm 更新
验证属性变更
```

## 13. 迁移步骤

1. 新增 `manage_graph_data.py`
2. 定义 `graph_change_plan` 格式
3. 把现有 `graph_data` 导入转换为 `create_*` operations
4. 实现 validate / dry-run / hash
5. 实现 delete_edge
6. 实现 update_vertex
7. 实现 update_edge
8. 实现 delete_vertex，默认 `cascade=false`
9. 接入 `server.py`
10. 保留 `import_graph_data_tool` 兼容转发
11. 补测试
12. 更新 README / PRD 文档
13. 做真实回归测试

## 14. 建议优先级

第一批：

```text
manage_graph_data_tool
delete_edge
update_vertex
dry-run / plan_hash / confirm
```

第二批：

```text
update_edge
delete_vertex cascade=false
import_graph_data_tool 兼容转发
```

第三批：

```text
自然语言删除/更新
批量操作
操作历史
```

## 15. 验收标准

### 15.1 删除关系

用户请求：

```text
删除 Alice 和 Bob 的 colleague 关系
```

dry-run 返回：

```text
将删除 1 条边：
Alice -[colleague {date: 2026-05-26}]-> Bob

不会删除：
Alice 顶点
Bob 顶点

plan_hash: ...
```

确认后：

```text
删除成功
Alice 和 Bob 仍存在
colleague 关系不存在
```

### 15.2 更新属性

用户请求：

```text
把 Alice 的 occupation 改为 工程师
```

dry-run 返回：

```text
将更新 1 个 person 顶点：
Alice.occupation = 工程师

plan_hash: ...
```

确认后：

```text
更新成功
查询 Alice 可看到 occupation=工程师
```

## 16. 风险和注意事项

- 删除能力必须默认保守，尤其是 `delete_vertex`。
- `cascade=true` 不应在第一批默认开放。
- 更新主键字段必须拒绝。
- 删除或更新匹配多个对象时默认拒绝。
- `execute_gremlin_write_tool` 仍应作为调试入口，不应成为普通用户路径。
- GraphRAG 问图当前不稳定，不应阻塞本计划。
