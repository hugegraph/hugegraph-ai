# HugeGraph MCP

[English](README.md)

HugeGraph MCP 是一个基于 FastMCP 的 Model Context Protocol Server。它把 HugeGraph 的常用操作收敛成少量高层能力，让 AI 助手可以查看图状态、查询图数据、管理 schema、管理图数据。

## 快速开始

### 前置条件

- HugeGraph Server，例如 `http://127.0.0.1:8080`，版本 1.7.0 或更高
- Python 3.10+
- `PATH` 中可用的 Git

### MCP 配置

在 IDE 或 AI 助手的 MCP 配置文件中加入 server 配置：

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
        "HUGEGRAPH_MCP_READONLY": "true"
      }
    }
  }
}
```

修改配置后，需要重启 IDE 或 AI 助手。

### 可选环境变量

所有环境变量都是可选项：

- `HUGEGRAPH_URL`，默认值：`http://127.0.0.1:8080`
- `HUGEGRAPH_GRAPH_PATH`，默认值：`DEFAULT/hugegraph`
- `HUGEGRAPH_USER`，默认值：`admin`
- `HUGEGRAPH_PASSWORD`，默认值：空字符串
- `HUGEGRAPH_MCP_READONLY`，默认值：`false`
- `HUGEGRAPH_MCP_ALLOW_AI`，默认值：`false`
- `HUGEGRAPH_AI_URL`，默认值：`http://127.0.0.1:8001`
- `HUGEGRAPH_AI_GRAPH_URL`，默认值：未设置
- `HUGEGRAPH_MCP_TIMEOUT_SECONDS`，默认值：`30`
- `HUGEGRAPH_MCP_MAX_CONTEXT_ITEMS`，默认值：`100`
- `HUGEGRAPH_MCP_SQL_ENABLED`，默认值：`false`
- `HUGEGRAPH_MCP_SQLITE_ALLOWLIST`，默认值：空字符串
- `HUGEGRAPH_MCP_SQL_MAX_PREVIEW_ROWS`，默认值：`20`
- `HUGEGRAPH_MCP_SQL_MAX_IMPORT_ROWS`，默认值：`1000`
- `HUGEGRAPH_MCP_SQL_TIMEOUT_SECONDS`，默认值：`10`

`HUGEGRAPH_GRAPH_PATH` 使用 `GRAPH_SPACE/GRAPH_NAME` 格式，例如 `DEFAULT/hugegraph`。

`HUGEGRAPH_MCP_READONLY` 和 `HUGEGRAPH_MCP_ALLOW_AI` 是两个独立开关：

- `HUGEGRAPH_MCP_READONLY=true` 会阻止 schema、图数据、索引和直接写 Gremlin 等会修改图的操作。
- `HUGEGRAPH_MCP_ALLOW_AI=true` 允许调用 HugeGraph-AI，包括自然语言生成 Gremlin、GraphRAG、自然语言抽取图数据。
- 两者可以同时为 `true`：允许 AI 辅助的读取、查询和抽取流程，但仍然阻止所有写入。

SQL 能力默认关闭。启用后当前只支持本地 SQLite，并且建议配置 allowlist 限制可访问文件：

```json
{
  "env": {
    "HUGEGRAPH_MCP_SQL_ENABLED": "true",
    "HUGEGRAPH_MCP_SQLITE_ALLOWLIST": "D:/data/hugegraph-import.sqlite3;D:/data/other.sqlite3"
  }
}
```

SQL 查询只允许只读语句，例如 `SELECT`、`WITH ... SELECT`、`EXPLAIN` 和信息类 `PRAGMA`。`INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`CREATE`、`REPLACE`、`ATTACH`、`DETACH` 等会被拒绝。SQL 导入只负责读取 SQL 结果集，再转换成 `table_data`，后续复用表格导入和图数据写入的安全链。

如果首次安装依赖较慢，可以先本地预安装 MCP server：

```bash
uvx --from git+https://github.com/hugegraph/hugegraph-ai.git@graph-mcp#subdirectory=hugegraph-mcp hugegraph-mcp
```

然后重启 IDE 或 AI 助手。

## 主要能力

所有高层工具都会返回统一 envelope：

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
    "readonly": true,
    "duration_ms": 0
  }
}
```

### 配套 Skills

Skills 是 agent 侧的工作流说明，用来帮助 AI 助手选择正确的 MCP 能力、组织 dry-run/confirm/verification/cleanup 流程，并规范输出。它们不是 MCP 协议的一部分，也不是权限边界；实际读写、只读校验、plan_hash 校验和权限 guard 仍由 MCP server 执行。

如果客户端支持 Skills，可以配置以下 5 个核心 Skill：

| Skill | 适用场景 | 主要 MCP 路径 |
| --- | --- | --- |
| `hugegraph-operator` | 查看图状态、schema、服务健康、权限状态、AI 可用性、计数和索引状态 | `inspect_graph_tool` |
| `hugegraph-query-analyst` | 查询图数据；自然语言生成 Gremlin 并只读执行；需要证据召回时使用 GraphRAG | `query_graph_tool` |
| `hugegraph-schema-designer` | 设计、校验、dry-run 和安全 apply schema 变更 | `manage_schema_tool` |
| `hugegraph-data-importer` | 从自然语言、结构化图数据、表格行或 SQL 结果导入图数据；更新和删除图数据 | `manage_graph_data_tool` |
| `hugegraph-regression-tester` | 对用户能力做真实回归测试，包括写入、验证、清理和权限行为检查 | 上述工具组合 |

建议把 Skill 用作“怎么调用 MCP”的操作指南，而不是绕过 MCP 的实现入口。例如导入数据时，Skill 会要求先 dry-run、记录 `plan_hash`、再 confirm 写入、最后查询验证和清理；真正的写入仍通过 `manage_graph_data_tool` 完成。

支持 Skills 的客户端通常会从本地 skills 目录加载，例如：

```text
$CODEX_HOME/skills/
  hugegraph-operator/
  hugegraph-query-analyst/
  hugegraph-schema-designer/
  hugegraph-data-importer/
  hugegraph-regression-tester/
```

### 1. 查看图状态和 Schema

连接 MCP 后建议先调用 `inspect_graph_tool`。它会检查 HugeGraph Server 状态、HugeGraph-AI 可用性、schema 摘要、图计数、索引计数、只读状态、warnings 和建议的下一步操作。该工具是 best-effort 的：如果部分后端能力不可用，会返回降级结果，而不是让整个检查失败。

基础检查：

```json
{
  "tool": "inspect_graph_tool",
  "arguments": {
    "include_raw_schema": false
  }
}
```

规划 schema 修改或排查 schema 不一致时，可以带上 raw schema：

```json
{
  "tool": "inspect_graph_tool",
  "arguments": {
    "include_raw_schema": true
  }
}
```

### 2. 查询图

使用 `query_graph_tool` 读取图数据。它支持三种模式：

- `text`：通过 HugeGraph-AI GraphRAG 进行自然语言问图。
- `generate`：把自然语言转换成 Gremlin。默认只生成查询，不执行。
- `gremlin`：直接执行已知安全的只读 Gremlin。

自然语言问图：

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "text",
    "query": "Alice 认识哪些人？",
    "rag_mode": "graph_only",
    "include_evidence": true,
    "max_context_items": 20
  }
}
```

只生成 Gremlin，不执行：

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "generate",
    "query": "查找出边 knows 最多的前 10 个人"
  }
}
```

生成 Gremlin，并且只在判定为只读时执行：

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "generate",
    "query": "按城市统计 person 顶点数量",
    "execute": true
  }
}
```

直接执行只读 Gremlin：

```json
{
  "tool": "query_graph_tool",
  "arguments": {
    "mode": "gremlin",
    "gremlin_query": "g.V().hasLabel('person').limit(10).valueMap(true)"
  }
}
```

### 3. 设计和管理 Schema

使用 `manage_schema_tool` 设计、校验、dry-run 和 apply schema 操作。会修改 schema 的操作必须走 `dry_run -> plan_hash -> confirm` 安全链。

请求 schema 设计建议：

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "design"
  }
}
```

在生成 apply 计划前校验 schema 操作：

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "validate",
    "operations": [
      {
        "type": "create_property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_vertex_label",
        "name": "person",
        "properties": ["name"],
        "primary_keys": ["name"]
      }
    ]
  }
}
```

创建 dry-run 计划，并记录返回的 `plan_hash`：

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "dry_run",
    "operations": [
      {
        "type": "create_property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_vertex_label",
        "name": "person",
        "properties": ["name"],
        "primary_keys": ["name"]
      }
    ]
  }
}
```

应用同一个 dry-run 计划：

```json
{
  "tool": "manage_schema_tool",
  "arguments": {
    "mode": "apply",
    "confirm": true,
    "plan_hash": "PLAN_HASH_FROM_DRY_RUN",
    "operations": [
      {
        "type": "create_property_key",
        "name": "name",
        "data_type": "TEXT",
        "cardinality": "SINGLE"
      },
      {
        "type": "create_vertex_label",
        "name": "person",
        "properties": ["name"],
        "primary_keys": ["name"]
      }
    ]
  }
}
```

### 4. 管理图数据

使用 `manage_graph_data_tool` 从自然语言抽取候选图数据、导入结构化图数据、把表格行或 SQL 查询结果映射成图数据、更新图元素、删除图元素。会修改图数据的操作必须走 `dry_run -> plan_hash -> confirm` 安全链。

从自然语言抽取候选图数据，不写入 HugeGraph：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "extract",
    "text": "Alice 在 Acme 工作。Bob 认识 Alice。"
  }
}
```

`schema` 参数是可选项。正常使用时建议省略它，让 HugeGraph-AI 使用当前图的 live schema。如果要手动传入 `schema`，需要传后端兼容的 live schema 结构，而不是简化的 label 列表。

对结构化图数据导入做 dry-run：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "import",
    "dry_run": true,
    "graph_data": {
      "vertices": [
        {"label": "person", "id": "alice", "properties": {"name": "Alice"}},
        {"label": "person", "id": "bob", "properties": {"name": "Bob"}}
      ],
      "edges": [
        {
          "label": "knows",
          "source_label": "person",
          "target_label": "person",
          "source": {"name": "Bob"},
          "target": {"name": "Alice"},
          "properties": {}
        }
      ]
    }
  }
}
```

应用同一个 dry-run 导入计划：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "import",
    "dry_run": false,
    "confirm": true,
    "plan_hash": "PLAN_HASH_FROM_DRY_RUN",
    "graph_data": {
      "vertices": [
        {"label": "person", "id": "alice", "properties": {"name": "Alice"}},
        {"label": "person", "id": "bob", "properties": {"name": "Bob"}}
      ],
      "edges": [
        {
          "label": "knows",
          "source_label": "person",
          "target_label": "person",
          "source": {"name": "Bob"},
          "target": {"name": "Alice"},
          "properties": {}
        }
      ]
    }
  }
}
```

把表格行映射成图数据，并进入同一套导入安全流程：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "table",
    "dry_run": true,
    "table_data": {
      "table_name": "employment",
      "columns": ["person_name", "company_name"],
      "rows": [
        ["Alice", "Acme"],
        ["Bob", "Acme"]
      ]
    },
    "mapping": {
      "vertex_mappings": [
        {
          "target_label": "person",
          "column_mapping": {"name": "person_name"},
          "primary_key_columns": ["person_name"]
        },
        {
          "target_label": "company",
          "column_mapping": {"name": "company_name"},
          "primary_key_columns": ["company_name"]
        }
      ],
      "edge_mappings": [
        {
          "target_label": "works_at",
          "source_vertex": {
            "label": "person",
            "primary_key_columns": ["person_name"]
          },
          "target_vertex": {
            "label": "company",
            "primary_key_columns": ["company_name"]
          },
          "column_mapping": {}
        }
      ]
    }
  }
}
```

#### 从 SQL 导入图数据

SQL 导入是表格导入的上游能力：先从 SQLite 执行只读 SQL，得到 `table_data`，再按 mapping 转成 `graph_data`，最后进入同一套 `dry_run -> plan_hash -> confirm` 写入流程。

当前 SQL source 只支持 SQLite：

```json
{
  "type": "sqlite",
  "path": "D:/data/hugegraph-import.sqlite3"
}
```

`path` 必须指向本地 SQLite 文件。如果配置了 `HUGEGRAPH_MCP_SQLITE_ALLOWLIST`，该路径必须在 allowlist 中。

预览一个 SQLite 表：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_preview",
    "sql_source": {
      "type": "sqlite",
      "path": "D:/data/hugegraph-import.sqlite3"
    },
    "table_name": "employee_relations"
  }
}
```

预览一个只读 SELECT 查询：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_preview",
    "sql_source": {
      "type": "sqlite",
      "path": "D:/data/hugegraph-import.sqlite3"
    },
    "sql_query": "SELECT source_name, target_name, work_date FROM employee_relations LIMIT 20"
  }
}
```

根据 SQL 结果列生成 mapping 建议：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_mapping_suggest",
    "sql_source": {
      "type": "sqlite",
      "path": "D:/data/hugegraph-import.sqlite3"
    },
    "sql_query": "SELECT source_name, target_name, work_date FROM employee_relations"
  }
}
```

mapping 建议是可编辑草稿。真实导入前应根据 live schema 检查 `target_label`、`column_mapping`、`primary_key_columns` 和边的 source/target 是否正确。

下面示例假设图中已经存在：

- 顶点类型 `person`，主键属性为 `name`
- 边类型 `colleague`，连接 `person -> person`，属性为 `date`

对 SQL 导入做 dry-run：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_import",
    "dry_run": true,
    "sql_source": {
      "type": "sqlite",
      "path": "D:/data/hugegraph-import.sqlite3"
    },
    "sql_query": "SELECT source_name, target_name, work_date FROM employee_relations",
    "table_name": "employee_relations",
    "mapping": {
      "vertex_mappings": [
        {
          "target_label": "person",
          "column_mapping": {"name": "source_name"},
          "primary_key_columns": ["source_name"]
        },
        {
          "target_label": "person",
          "column_mapping": {"name": "target_name"},
          "primary_key_columns": ["target_name"]
        }
      ],
      "edge_mappings": [
        {
          "target_label": "colleague",
          "source_vertex": {
            "label": "person",
            "primary_key_columns": ["source_name"]
          },
          "target_vertex": {
            "label": "person",
            "primary_key_columns": ["target_name"]
          },
          "column_mapping": {"date": "work_date"}
        }
      ]
    }
  }
}
```

应用同一个 SQL 导入 dry-run 计划：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "sql_import",
    "dry_run": false,
    "confirm": true,
    "plan_hash": "PLAN_HASH_FROM_DRY_RUN",
    "sql_source": {
      "type": "sqlite",
      "path": "D:/data/hugegraph-import.sqlite3"
    },
    "sql_query": "SELECT source_name, target_name, work_date FROM employee_relations",
    "table_name": "employee_relations",
    "mapping": {
      "vertex_mappings": [
        {
          "target_label": "person",
          "column_mapping": {"name": "source_name"},
          "primary_key_columns": ["source_name"]
        },
        {
          "target_label": "person",
          "column_mapping": {"name": "target_name"},
          "primary_key_columns": ["target_name"]
        }
      ],
      "edge_mappings": [
        {
          "target_label": "colleague",
          "source_vertex": {
            "label": "person",
            "primary_key_columns": ["source_name"]
          },
          "target_vertex": {
            "label": "person",
            "primary_key_columns": ["target_name"]
          },
          "column_mapping": {"date": "work_date"}
        }
      ]
    }
  }
}
```

如果 `sql_import` 没有传入完整 mapping，它不会直接写图，而是返回 `mapping_suggestion`，用于人工检查后再次提交。SQL 导入的 `plan_hash` 会绑定 SQL source、SQL query、mapping 和图变更计划；确认写入时必须传回同一个 dry-run 返回的 `plan_hash`。

对图元素更新做 dry-run：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "update",
    "dry_run": true,
    "change_plan": {
      "operations": [
        {
          "op": "update_vertex",
          "label": "person",
          "match": {"name": "Alice"},
          "set": {"age": 31}
        }
      ]
    }
  }
}
```

对图元素删除做 dry-run：

```json
{
  "tool": "manage_graph_data_tool",
  "arguments": {
    "mode": "delete",
    "dry_run": true,
    "change_plan": {
      "operations": [
        {
          "op": "delete_vertex",
          "label": "person",
          "match": {"name": "Alice"},
          "cascade": false
        }
      ]
    }
  }
}
```

`import_graph_data_tool` 仍然保留用于兼容旧流程。新流程优先使用 `manage_graph_data_tool`。

## 高级调试工具

以下工具用于维护和调试。普通用户流程建议优先使用上面的四类高层能力。

### `execute_gremlin_write_tool`

直接执行 Gremlin 写查询。常规图数据写入应优先使用 `manage_graph_data_tool` 的 `mode="import"`，因为它会做数据校验，并使用 dry-run 安全链。

```json
{
  "tool": "execute_gremlin_write_tool",
  "arguments": {
    "gremlin_query": "g.addV('person').property('name', 'Alice')"
  }
}
```

### `refresh_vid_embeddings_tool`

通过 HugeGraph-AI 刷新 VID embeddings。这是会修改索引的操作，需要显式确认。

```json
{
  "tool": "refresh_vid_embeddings_tool",
  "arguments": {
    "confirm": true
  }
}
```

## 权限模型

MCP server 使用环境变量开关和运行时能力 guard 控制权限。它目前不提供按用户划分的 RBAC。

`HUGEGRAPH_MCP_READONLY` 和 `HUGEGRAPH_MCP_ALLOW_AI` 是独立控制：

- `HUGEGRAPH_MCP_READONLY=true` 阻止图侧写入。
- `HUGEGRAPH_MCP_ALLOW_AI=true` 允许调用 HugeGraph-AI，用于自然语言生成查询、GraphRAG 和图数据抽取。
- 两者同时为 `true` 时，可以进行 AI 辅助的读、查、抽取，但仍然拒绝图写入。

| 能力 | 使用场景 | `readonly=true` 行为 |
| --- | --- | --- |
| `READ` | 图状态、schema 查看、直接只读图查询 | 允许 |
| `GENERATE` | 仅生成计划或查询，不直接写入 | 允许 |
| `DATA_WRITE` | 图数据导入、更新、删除的 apply 路径 | 拒绝 |
| `SCHEMA_WRITE` | schema apply 路径 | 拒绝 |
| `INDEX_WRITE` | VID embedding 刷新 | 拒绝 |
| `DEBUG_WRITE` | 直接 Gremlin 写调试工具 | 拒绝 |

各工具在该模型下的行为：

| 工具 | 行为 |
| --- | --- |
| `inspect_graph_tool` | 始终允许。返回图状态、schema 摘要、可用时的计数和 AI 状态。 |
| `query_graph_tool` | 允许执行只读 Gremlin。AI 生成和 GraphRAG 模式要求 `HUGEGRAPH_MCP_ALLOW_AI=true`。 |
| `manage_schema_tool` | 设计、校验、dry-run 允许。apply 需要 `readonly=false`、之前的 dry-run、匹配的 `plan_hash` 和 `confirm=true`。 |
| `manage_graph_data_tool` | 自然语言抽取、表格映射、SQL 预览、SQL mapping 建议和 dry-run 允许；其中 AI 抽取依赖 `HUGEGRAPH_MCP_ALLOW_AI=true`，SQL 能力依赖 `HUGEGRAPH_MCP_SQL_ENABLED=true` 和 SQLite allowlist。import、sql_import、update、delete 的 apply 路径需要 `readonly=false`、之前的 dry-run、匹配的 `plan_hash` 和 `confirm=true`。 |
| `import_graph_data_tool` | 图数据导入兼容入口。新流程建议使用 `manage_graph_data_tool`。 |
| `refresh_vid_embeddings_tool` | 需要 `readonly=false` 和 `confirm=true`。 |
| `execute_gremlin_write_tool` | 需要 `readonly=false`。仅建议用于调试和管理员维护，不建议作为常规数据导入入口。 |

## 安全说明

- 探索、演示和生产只读助手场景建议设置 `HUGEGRAPH_MCP_READONLY=true`。
- 只有当部署环境允许调用 HugeGraph-AI 时，才设置 `HUGEGRAPH_MCP_ALLOW_AI=true`。
- 只读模式会在运行时阻止写路径，包括 schema 修改、图数据 import/update/delete apply、直接 Gremlin 写、embedding 刷新。
- schema apply 和图数据 import/update/delete apply 都要求先执行 dry-run，再使用匹配的 `plan_hash` 和 `confirm=true`。
- `query_graph_tool` 的 `mode="generate"` 默认不会执行生成出来的 Gremlin，除非显式传入 `execute=true`。
- 直接 Gremlin 读取只有在 traversal 可被判定为只读时才允许执行。不安全或无法确认的 traversal 会被拒绝。
- 不要把直接写 Gremlin 调试工具作为常规数据导入方式。
- SQL 能力只读取 allowlist 内的本地 SQLite 文件，并且只接受只读 SQL。SQL 导入最终仍会进入图数据写入安全链。

## License

Apache License 2.0
