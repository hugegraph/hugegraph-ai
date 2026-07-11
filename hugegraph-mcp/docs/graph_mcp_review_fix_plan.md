# HugeGraph MCP Review Fix Plan

本文档基于 `graph-mcp` 分支对 `hugegraph-mcp` 模块的审查结果，拆解后续修复任务、具体改动点和验收标准。

目标是把当前分支从“功能可用”推进到“可稳定评审、可真实 HugeGraph 回归、错误语义可信、后续易维护”的状态。

## 0. 当前修复状态

截至本轮修复，Phase 0、Phase 1、Phase 2 和 Phase 3 的核心项已落地：

- Phase 0: diff check、ruff check、format check、pytest marker 入口已修复；2026-07-06 复核发现的 `tests/test_manage_schema.py` 格式化漂移已重新格式化。
- Phase 1: PRIMARY_KEY schema 校验、badcase 错误分类、edge id URL 编码均已修复并补测试。
- Phase 2: toolset 生效时机、AI disabled 语义、table import disabled suggestion 已同步到代码和文档。
- Phase 3: 已抽取轻量 `confirmable_workflow` helper，并接入 schema/data/mutate 三条写入确认链路。
- Post-review: `mutate_graph_properties` post-read 异常已在 success data 中脱敏；schema object missing 已优先归类为 `SCHEMA_MISMATCH`；admin/debug 和 table import 的 `FEATURE_DISABLED` 文案已去掉误导性的 V1 表述；README 已明确默认 `v2_core` 注册 13 个工具，其中 11 个普通稳定工具、2 个 admin/debug 工具默认阻断。
- 真实 HG 测试已新增 edge by-id typed query 与 edge property append/eliminate 覆盖；schema 创建后增加可见性等待，降低服务端异步可见性导致的瞬态失败。

本轮已复跑并通过：

```bash
uv run --project hugegraph-mcp ruff format --check hugegraph-mcp
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_error_handling.py hugegraph-mcp/tests/test_mutate_graph_properties_tool.py hugegraph-mcp/tests/test_v1_stable_tools.py hugegraph-mcp/tests/test_import_graph_data_tool.py hugegraph-mcp/tests/test_manage_schema.py -q
RUN_MCP_REAL_HUGEGRAPH_TESTS=1 uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/integration/test_real_write_path.py -vv
```

真实 HugeGraph 集成测试本轮已在本机环境通过；合入前仍建议在 PR 描述中记录 HugeGraph Server 版本、图空间、图名和命令输出摘要。

## 1. 修复原则

- 先修确定性阻塞项，再修真实行为问题，最后做结构治理。
- 每个行为修复必须有至少一个对应单元测试；涉及 HugeGraph Server 行为的修复必须补真实 HG 回归测试。
- 不扩大公开 MCP 工具契约；只修正当前 `v2_core` / `v1` 已声明能力。
- 不把 HugeGraph Server 自身限制包装成 MCP 功能缺失；错误信息需要明确区分“服务端限制”“输入错误”“连接失败”“功能禁用”。
- 所有写路径继续保留 `dry_run -> plan_hash -> confirm` 安全链。

## 2. 总体验收门槛

全部修复完成后，必须通过以下检查：

```bash
cd /Users/uleng/Code/hugegraph-ai

git diff --check apache/main...HEAD -- hugegraph-mcp
uv run --project hugegraph-mcp ruff check hugegraph-mcp
uv run --project hugegraph-mcp ruff format --check hugegraph-mcp
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests -m "not live and not integration and not real_hugegraph and not llm"
RUN_MCP_REAL_HUGEGRAPH_TESTS=1 uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/integration/test_real_write_path.py -vv
```

如果本地 HugeGraph Server 不可用，真实 HG 测试可以暂缓，但必须在 PR 合入前补跑，并在 PR 描述中写明 HugeGraph Server 版本、图空间、图名和命令输出摘要。

## 3. 分阶段修复计划

| 阶段 | 优先级 | 目标 | 允许合并到下一阶段的条件 |
| --- | --- | --- | --- |
| Phase 0 | P0 | 清理发布和 CI 阻塞项 | diff check、ruff check、format check、非真实 HG 测试全部通过 |
| Phase 1 | P1 | 修正会影响真实使用的行为问题 | 新增 badcase 单测通过，真实 HG 写路径通过 |
| Phase 2 | P2 | 修正文档契约和错误提示 | README 与实际行为一致，错误码和 suggestion 可操作 |
| Phase 3 | P2/P3 | 降低后续维护成本 | 重复确认链路和错误映射收敛，现有测试不退化 |

## 4. Phase 0: 发布卫生和测试入口

### Fix-00: 清理格式和空白问题

**问题**

- `git diff --check` 报告 `hugegraph_mcp/__init__.py` 文件尾部多余空行。
- `ruff format --check` 报告 5 个文件需要格式化：
  - `hugegraph_mcp/tools/inspect_schema.py`
  - `hugegraph_mcp/tools/manage_schema.py`
  - `hugegraph_mcp/tools/mutate_graph_properties.py`
  - `hugegraph_mcp/tools/query_graph_data.py`
  - `tests/test_manage_schema.py`

**具体修复**

1. 删除 `hugegraph_mcp/__init__.py` 末尾多余空行。
2. 执行 `uv run --project hugegraph-mcp ruff format hugegraph-mcp`。
3. 检查格式化 diff，确认没有引入行为变化。

**验收标准**

```bash
git diff --check apache/main...HEAD -- hugegraph-mcp
uv run --project hugegraph-mcp ruff format --check hugegraph-mcp
uv run --project hugegraph-mcp ruff check hugegraph-mcp
```

三条命令必须全部通过。

### Fix-01: 统一 pytest markers

**问题**

根 `pyproject.toml` 开启了 `--strict-markers --strict-config`，但真实 HG 测试使用的 `real_hugegraph`、`live`、`llm` markers 只在 `hugegraph-mcp/pyproject.toml` 中声明。从仓库根收集测试时，存在 unknown marker 失败风险。

**具体修复**

1. 在根 `pyproject.toml` 的 `[tool.pytest.ini_options].markers` 中补充：
   - `live: requires a real HugeGraph Server`
   - `real_hugegraph: requires a real HugeGraph Server`
   - `llm: requires HugeGraph-AI or an external LLM provider`
2. 保留 `hugegraph-mcp/pyproject.toml` 中的 markers，除非确认模块独立运行不再需要。
3. 补充一条文档说明：推荐从 `uv run --project hugegraph-mcp pytest ...` 运行 MCP 测试。

**验收标准**

```bash
uv run pytest --collect-only hugegraph-mcp/tests/integration/test_real_write_path.py
uv run --project hugegraph-mcp pytest --collect-only hugegraph-mcp/tests/integration/test_real_write_path.py
```

两条命令都不能出现 unknown marker 或 strict config 错误。

## 5. Phase 1: 行为正确性和严谨性

### Fix-10: PRIMARY_KEY vertex label 必须有 primary_keys

**问题**

`create_vertex_label` 默认 `id_strategy=PRIMARY_KEY`，但缺少 `primary_keys` 时当前只产生 warning。这样 dry-run 可能返回 `valid=true` 和 `plan_hash`，真正 apply 时才失败，并且可能已经创建了前面的 property keys，造成部分写入。

**具体修复**

1. 修改 `hugegraph_mcp/tools/manage_schema.py` 的 schema operation 校验逻辑。
2. 当 `type=create_vertex_label` 且 `id_strategy` 为空或 `PRIMARY_KEY` 时：
   - `primary_keys` 必须是非空列表。
   - `primary_keys` 中的每个字段必须出现在该 vertex label 的 `properties` 中。
   - `primary_keys` 中的每个字段必须已经存在于 live schema，或在同批 `create_property_key` 操作中创建。
3. 对 `id_strategy=AUTOMATIC`、`CUSTOMIZE_STRING`、`CUSTOMIZE_NUMBER` 不强制要求 `primary_keys`。
4. 将当前“无 primary_keys warning”改成只对非 PRIMARY_KEY 策略保留，或直接删除该 warning。

**需要新增或调整的测试**

- `tests/test_manage_schema.py`
  - `PRIMARY_KEY` 缺少 `primary_keys` 时，`dry_run` 返回 `valid=false`。
  - `PRIMARY_KEY` 的 `primary_keys` 不在 `properties` 中时，返回 validation error。
  - `PRIMARY_KEY` 引用不存在的 property key 时，返回 validation error。
  - `AUTOMATIC` 不提供 `primary_keys` 时仍可 dry-run 成功。

**验收标准**

- 缺主键的 PRIMARY_KEY schema 不再返回 `plan_hash`。
- dry-run 阶段即可阻断会导致 apply 半路失败的输入。
- 以下命令通过：

```bash
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_manage_schema.py -v
```

### Fix-11: edge id 查询和属性修改必须处理 URL reserved characters

**问题**

HugeGraph edge id 可能包含 `>`、`:` 等 URL path reserved characters。当前 `query_graph_data_tool` 的 edge `get_by_id`、`mutate_graph_properties_tool` 的 edge target fetch 和 edge append/eliminate 直接传 raw edge id 给 pyhugegraph。如果底层 client 未编码 path 参数，真实请求可能失败或命中错误路径。

**具体修复**

优先方案：

1. 在 `hugegraph-python-client` 的 edge-by-id URL 构造层统一 URL encode path 参数。
2. 确认 vertex id 和 edge id 的 path 参数都不会被重复编码。
3. 在 `hugegraph-mcp` 侧保留原始 id 作为业务 id，不在多个调用点重复编码。

备选方案：

1. 如果不改 client，则在 MCP 内新增一个很薄的 HugeGraph edge id helper。
2. 所有 edge by-id 读取、append、eliminate 都通过同一个 helper 调用。
3. 禁止各工具自行拼接或自行编码。

**需要新增或调整的测试**

- `hugegraph-python-client` 若修改 client：
  - URL router/path format 测试覆盖 `S1:alice>11>...` 这类 edge id。
- `hugegraph-mcp/tests/test_query_graph_data_tool.py`
  - mock client 断言 edge id 不被 MCP 破坏。
- `hugegraph-mcp/tests/test_mutate_graph_properties_tool.py`
  - mock client 断言 edge mutate 使用统一 helper。
- `hugegraph-mcp/tests/integration/test_real_write_path.py`
  - 创建两个 vertex 和一条 edge。
  - 从写入结果或查询结果拿真实 edge id。
  - 用 `query_graph_data_tool(target="edge", operation="get_by_id")` 查询成功。
  - 用 `mutate_graph_properties_tool(target="edge")` append/eliminate 一个 nullable property 成功。

**验收标准**

- 真实 HugeGraph 上，包含 reserved characters 的 edge id 可以完成 get、append、eliminate。
- 修复不改变公开 MCP 参数形态，用户仍传 HugeGraph 原始 edge id。
- 以下命令通过：

```bash
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_query_graph_data_tool.py hugegraph-mcp/tests/test_mutate_graph_properties_tool.py -v
RUN_MCP_REAL_HUGEGRAPH_TESTS=1 uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/integration/test_real_write_path.py -vv
```

### Fix-12: badcase 错误分类必须准确

**问题**

当前错误映射过于粗糙：

- HugeGraph no-index 错误只匹配 `noindexexception` 或 `no index`，不能覆盖真实错误文本中的 `not indexed` / `may not match secondary condition`。
- mutation 目标不存在时，从 `getVertexById` / `getEdgeById` 抛出的 NotFound 类错误被包装为 `CONNECTION_FAILED`，用户会误以为是连接问题。

**具体修复**

1. 新增或扩展统一错误分类 helper，例如 `hugegraph_mcp/error_mapping.py`。
2. no-index 判断至少覆盖：
   - `noindexexception`
   - `no index`
   - `not indexed`
   - `may not match secondary condition`
3. target not found 判断至少覆盖：
   - HTTP 404
   - `NotFound`
   - `not found`
   - HugeGraph 返回体中明确的 vertex/edge 不存在信息
4. `query_graph_data_tool` 对 no-index 返回：
   - `error_type=NO_INDEX`
   - `retryable=false`
   - suggestion 指向创建索引或改用 exact id 查询。
5. `mutate_graph_properties_tool` 对目标不存在返回：
   - `error_type=NOT_FOUND`，如果当前 `ErrorType` 没有该枚举，则新增。
   - `retryable=false`
   - suggestion 指向确认 id、target 类型和图空间。

**需要新增或调整的测试**

- `tests/test_query_graph_data_tool.py`
  - 模拟 `not indexed` 文本，断言 `NO_INDEX`。
  - 模拟 `may not match secondary condition` 文本，断言 `NO_INDEX`。
- `tests/test_mutate_graph_properties_tool.py`
  - 模拟 vertex 404，断言 `NOT_FOUND`。
  - 模拟 edge 404，断言 `NOT_FOUND`。
- `tests/test_error_handling.py`
  - 如果新增统一 error mapper，在这里补纯函数测试。

**验收标准**

- badcase 不再统一掉进 `SERVER_ERROR` 或 `CONNECTION_FAILED`。
- 错误响应中的 `suggestion` 能指导下一步动作。
- 以下命令通过：

```bash
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_query_graph_data_tool.py hugegraph-mcp/tests/test_mutate_graph_properties_tool.py hugegraph-mcp/tests/test_error_handling.py -v
```

## 6. Phase 2: 文档契约和用户提示

### Fix-20: 明确 HUGEGRAPH_MCP_TOOLSET 的生效时机

**问题**

README 把 `HUGEGRAPH_MCP_TOOLSET` 描述为公开工具契约选择器，但该变量不在 `CONFIG_ENV_NAMES` 中。实际工具注册发生在 server import / startup 期间，用户容易误以为它和普通 config 一样可被运行期缓存刷新感知。

**具体修复**

1. 在 README 和中文 README 的 Toolset Selection 段落明确：
   - `HUGEGRAPH_MCP_TOOLSET` 在 MCP server 启动和工具注册时生效。
   - 修改该变量后需要重启 MCP server。
2. 在 `inspect_graph_tool` 输出中继续展示当前 toolset。
3. 可选：将 `HUGEGRAPH_MCP_TOOLSET` 加入配置诊断元数据，但不要让它暗示运行期可热切换。

**验收标准**

- README 明确写出“修改后需要重启 MCP server”。
- `inspect_graph_tool` 仍能显示当前 toolset。
- 文档没有承诺热更新。

### Fix-21: AI disabled 错误语义可操作

**问题**

`HUGEGRAPH_MCP_ALLOW_AI=false` 时，AI 请求返回 `HUGEGRAPH_AI_UNAVAILABLE` 和 `AI calls are disabled`，但没有 suggestion。用户难以区分“功能被配置关闭”和“AI 服务不可用”。

**具体修复**

推荐方案：

1. 当 `allow_ai=false` 时返回 `FEATURE_DISABLED`。
2. suggestion 写明：设置 `HUGEGRAPH_MCP_ALLOW_AI=true` 并重启 MCP server，或使用不依赖 AI 的工具。
3. details 保留 `method` 和 `url`，但不要泄露密码、token 或 auth header。

兼容方案：

1. 继续返回 `HUGEGRAPH_AI_UNAVAILABLE`。
2. message 改为 `AI calls are disabled by configuration`。
3. 必须增加 suggestion 和 `details.reason=allow_ai_false`。

**需要新增或调整的测试**

- `tests/test_hugegraph_ai_client.py`
  - `allow_ai=false` 时断言 error_type、message、suggestion、retryable。

**验收标准**

- 用户能从错误响应直接判断是否需要改配置。
- 不泄露认证信息。

### Fix-22: 修正 table import disabled suggestion

**问题**

`import_graph_data_tool(mode="table")` 返回的 suggestion 写成 `Use mode='extract' with extract_graph_data_tool instead`，但实际公开入口是 `import_graph_data_tool(mode="extract")`。

**具体修复**

1. 修改 `server.py` 中 `mode=="table"` 的 suggestion。
2. 推荐文案：
   - `Use import_graph_data_tool(mode='extract') for text extraction, then import_graph_data_tool(mode='ingest') for validated graph_data.`

**需要新增或调整的测试**

- `tests/test_import_graph_data_tool.py`
  - 断言 table disabled 响应中的 suggestion 包含正确入口。

**验收标准**

- 文案不再引用不存在或误导性的调用方式。

## 7. Phase 3: 可维护性治理

### Fix-30: 收敛 HugeGraph 错误映射

**问题**

Gremlin、typed query、mutation 等工具各自用字符串匹配 HugeGraph 错误，导致同类错误在不同入口返回不同 `error_type`、`retryable` 和 suggestion。

**具体修复**

1. 新增统一错误映射模块，例如：
   - `hugegraph_mcp/error_mapping.py`
2. 提供纯函数：
   - `classify_hugegraph_exception(exc) -> ErrorClassification`
   - `classify_hugegraph_error_message(message) -> ErrorClassification`
3. `ErrorClassification` 至少包含：
   - `error_type`
   - `retryable`
   - `suggestion`
   - `reason`
4. 先接入 `query_graph_data_tool` 和 `mutate_graph_properties_tool`。
5. 第二步再评估是否接入 `gremlin_tools.py`，避免一次性改动过大。

**验收标准**

- no-index、not-found、connection 类错误的分类测试集中在一个测试文件中。
- 工具层只补充 `source`、`target`、`id` 等上下文，不再重复散落字符串匹配。

### Fix-31: 抽象 confirmable write workflow

**问题**

schema、graph data、ingest 等路径都实现了类似的 `dry_run -> plan_hash -> readonly -> confirm -> execute -> verify` 状态机。重复实现会让安全链、过期提示、hash context 和错误码逐步漂移。

**具体修复**

1. 先不要大规模重写业务逻辑。
2. 新增内部 helper，例如 `hugegraph_mcp/confirmable_workflow.py`。
3. 第一阶段只抽公共校验：
   - readonly preview 处理。
   - `confirm=true` 时 required fields 检查。
   - `plan_hash` / `nonce` / `expires_at` 校验错误包装。
4. 第二阶段再抽执行模板：
   - `validate_payload`
   - `build_plan_context`
   - `execute`
   - `verify`
5. 每接入一个工具，就保留原测试并新增至少一个 stale plan / readonly / expired plan 回归测试。

**验收标准**

- schema/data/import 三类写路径在 readonly、plan mismatch、plan expired 时返回一致错误结构。
- 现有 plan_hash 测试和 write-path 测试全部通过。
- PR diff 中业务逻辑变化可审查，不出现一次性大搬迁导致行为难以确认。

## 8. 建议 PR 拆分

| PR | 包含修复 | 原因 |
| --- | --- | --- |
| PR-1 | Fix-00, Fix-01 | 纯工程卫生和测试入口，风险低，先解除阻塞 |
| PR-2 | Fix-10, Fix-12 | schema 严谨性和 badcase 错误语义，影响用户输入校验 |
| PR-3 | Fix-11 | edge id 可能涉及 `hugegraph-python-client`，需要独立评审和真实 HG 验证 |
| PR-4 | Fix-20, Fix-21, Fix-22 | 文档和错误提示契约修复 |
| PR-5 | Fix-30, Fix-31 | 维护性治理，等行为稳定后再做 |

## 9. 最终验收清单

修复完成后，逐项确认：

- [ ] `git diff --check apache/main...HEAD -- hugegraph-mcp` 通过。
- [ ] `ruff check` 和 `ruff format --check` 通过。
- [ ] 非真实 HG 测试通过，且新增 badcase 测试覆盖本计划中的所有错误路径。
- [ ] 真实 HG 测试通过，至少覆盖 schema create、data import、typed query、edge by-id、edge mutate、delete、readonly gate；当前新增 `test_edge_by_id_query_and_mutate_handles_real_hugegraph_edge_id` 覆盖 edge by-id 与 edge mutate。
- [ ] README 和 README.zh-CN 对 toolset、AI disabled、table disabled、schema apply 范围描述一致。
- [ ] 所有写路径仍需要 `dry_run -> plan_hash -> confirm`，readonly 默认仍阻断写入。
- [ ] PR 描述列出未修的 HugeGraph Server 原生限制，例如 no-index 查询限制和 paging+filtering 限制，避免被误解为 MCP 功能不可用。
