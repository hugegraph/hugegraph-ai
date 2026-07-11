# Graph MCP Post-Review Fix Plan

本文档记录当前 `graph-mcp` 分支复核后仍需处理的问题、修复顺序、涉及文件和验收命令。

## 1. 复核结论

当前分支相对 `github/graph-mcp` 的 MCP/client 修复整体方向正确，核心安全链没有发现被削弱：

- readonly/admin gate 仍在执行期生效。
- `dry_run -> plan_hash -> confirm` 仍会绑定 payload、schema、target、readonly、nonce 和 expiry。
- edge id path/query 编码覆盖 `getEdgeById`、`appendEdge`、`eliminateEdge`、`removeEdgeById`、`getEdgesById`。

但合入前仍有以下问题需要修复：

| 优先级 | 问题 | 结论 |
| --- | --- | --- |
| Blocker | `ruff format --check` 失败 | 必须修复后才能合入 |
| High | `mutate_graph_properties` 的 success data 可能绕过脱敏 | 必须修复并补测试 |
| Medium | `FEATURE_DISABLED` 文案残留 `V1` | 需要修正文案和测试 |
| Low/Medium | `NOT_FOUND` 分类过宽 | 建议修复，避免误导用户 |
| Low | README 工具数量口径不够清晰 | 建议同步修正 |

## 2. 问题明细

### 2.1 格式门禁失败

涉及文件：

- `hugegraph-mcp/tests/test_manage_schema.py`

复核命令：

```bash
uv run --project hugegraph-mcp ruff format --check hugegraph-mcp
```

当前结果：

```text
Would reformat: hugegraph-mcp/tests/test_manage_schema.py
1 file would be reformatted, 56 files already formatted
```

影响：

- CI / pre-merge format gate 会失败。
- `docs/graph_mcp_review_fix_plan.md` 中关于 Phase 0 format check 已修复的状态与实际不一致。

修复要求：

- 运行 `ruff format` 修复该文件。
- 仅接受机械格式化 diff，不混入行为改动。

### 2.2 post-read error 绕过脱敏

涉及文件：

- `hugegraph-mcp/hugegraph_mcp/tools/mutate_graph_properties.py`
- `hugegraph-mcp/tests/test_mutate_graph_properties_tool.py`

现状：

`mutate_graph_properties._execute_and_verify()` 在写入返回但 post-read 验证异常时，会把 `str(exc)` 放入成功响应：

```python
"post_read_error": str(exc)
```

`envelope_ok()` 不会对 `data` 做 `sanitize_for_response()`，脱敏只覆盖 `envelope_err()` 的 `message`、`suggestion` 和 `details`。

影响：

- 如果异常文本包含 `Authorization`、`token=`、URL userinfo、password 等敏感信息，会在 `data.post_read_error` 中原样返回。
- 这是 MCP 实现问题，不是 HugeGraph Server 限制。

修复要求：

- 在该分支中使用 `sanitize_for_response(str(exc))`。
- 或将 post-read verification failure 改为标准错误 envelope，同时保留 `status="unknown"` 和补偿建议。
- 推荐最小修复：只对 `post_read_error` 脱敏，保持当前 `ok=true` + warning 的兼容行为。

测试要求：

- 模拟 mutation 执行成功，但 post-read 抛出包含以下内容的异常：
  - `Authorization: Bearer abc123`
  - `token=xyz`
  - `http://user:pass@example.com`
- 断言响应中不包含原始 secret、token 或 URL userinfo。
- 断言 `status` 仍为 `unknown`，next action 仍提示用户查询目标状态。

### 2.3 FEATURE_DISABLED 文案残留 V1

涉及文件：

- `hugegraph-mcp/hugegraph_mcp/server.py`
- `hugegraph-mcp/tests/test_v1_stable_tools.py`
- `hugegraph-mcp/tests/test_import_graph_data_tool.py`

现状：

`_admin_gate()` 返回：

```text
<tool> is disabled by default in V1. Enable with HUGEGRAPH_MCP_ADMIN_MODE=true.
```

`import_graph_data_tool(mode="table")` 返回：

```text
Table import is not available in V1.
```

影响：

- 当前默认工具集是 `v2_core`，该文案会误导用户以为自己处于 V1，或需要切换 toolset。
- 实际下一步应该是开启 admin mode、关闭 readonly，或改用当前支持的 `extract -> ingest` 路径。

修复要求：

- admin/debug 工具禁用文案改为能力维度：

```text
<tool> is an admin/debug tool and is disabled by default.
```

- write-capable admin/debug 工具 suggestion 保持指向：

```text
Set HUGEGRAPH_MCP_ADMIN_MODE=true and HUGEGRAPH_MCP_READONLY=false to enable <tool>.
```

- table import 文案改为：

```text
Table import is not supported by the current MCP contract.
```

- `details` 建议增加当前 `toolset` 和需要设置的环境变量。

测试要求：

- 默认 `v2_core` 下调用 admin/debug 工具，错误信息不再包含 `V1`。
- `mode="table"` 的 `FEATURE_DISABLED` 不再包含 `V1`，suggestion 仍指向 `extract -> ingest`。

### 2.4 NOT_FOUND 分类过宽

涉及文件：

- `hugegraph-mcp/hugegraph_mcp/error_mapping.py`
- `hugegraph-mcp/tests/test_error_handling.py`

现状：

`NOT_FOUND_MARKERS` 包含：

```python
"404",
"notfound",
"not found",
"not exist",
"does not exist",
```

因此以下文本都会被分类为 `NOT_FOUND`：

```text
Property key does not exist: age
Edge label does not exist: knows
Vertex does not exist: 1
```

影响：

- 顶点/边目标不存在时返回 `NOT_FOUND` 是正确的。
- property key / vertex label / edge label / schema object 不存在时，用户更需要检查 schema 或属性名，而不是检查 id、target type、graphspace。

修复要求：

- 在 `NO_INDEX` 判断之后、通用 `NOT_FOUND` 判断之前，增加 schema-object missing 分类。
- 推荐分类为 `SCHEMA_MISMATCH`。
- suggestion 指向检查 live schema、label、property key。

建议 marker：

```python
SCHEMA_OBJECT_MISSING_MARKERS = (
    "property key does not exist",
    "propertykey does not exist",
    "vertex label does not exist",
    "vertexlabel does not exist",
    "edge label does not exist",
    "edgelabel does not exist",
    "schema does not exist",
)
```

测试要求：

- `Property key does not exist: age` -> `SCHEMA_MISMATCH`
- `Edge label does not exist: knows` -> `SCHEMA_MISMATCH`
- `Vertex does not exist: 1` -> `NOT_FOUND`
- `NoIndexException` / `not indexed` 仍优先为 `NO_INDEX`

### 2.5 README 工具口径不够清晰

涉及文件：

- `hugegraph-mcp/README.md`
- `hugegraph-mcp/README.zh-CN.md`

现状：

- README 先列出 11 个普通用户稳定工具。
- 随后说明 2 个 admin/debug 工具仍注册但默认阻断。
- toolset 表中写 `v2_core=13`、`v1=10`。

工具数量本身与代码一致，但读者容易误以为 README 少列了两个工具，或把 admin/debug 工具当成普通用户稳定工具。

修复要求：

- 明确默认 `v2_core` 注册 13 个 MCP 工具：
  - 11 个普通用户稳定工具。
  - 2 个 admin/debug 工具，默认注册但受 admin mode 阻断。

建议英文表述：

```text
The default `v2_core` toolset registers 13 MCP tools: 11 normal user-facing stable tools plus 2 admin/debug tools that are registered but blocked by default.
```

建议中文表述：

```text
默认 `v2_core` 工具集注册 13 个 MCP 工具：其中 11 个是普通用户稳定工具，另外 2 个是管理/调试工具，默认注册但受 admin mode 阻断。
```

### 2.6 修复计划状态同步

涉及文件：

- `hugegraph-mcp/docs/graph_mcp_review_fix_plan.md`

现状：

该文档顶部声明 Phase 0 的 format check 已修复，但当前 format check 实际失败。

修复要求：

- 如果本轮修复后格式门禁通过，可以保留 Phase 0 已修复状态，并补充本轮 post-review 问题已处理。
- 如果真实 HugeGraph 集成测试未复跑，不要声明当前已通过，只写待补跑或引用最新实际命令结果。

## 3. 修复顺序

### Phase 1: 安全脱敏

1. 修改 `mutate_graph_properties.py`：
   - 引入 `sanitize_for_response`。
   - 对 `post_read_error` 使用脱敏后的异常文本。
2. 修改 `test_mutate_graph_properties_tool.py`：
   - 新增 post-read 异常脱敏测试。

验收命令：

```bash
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_mutate_graph_properties_tool.py -q
```

### Phase 2: 错误分类

1. 修改 `error_mapping.py`：
   - 新增 schema-object missing markers。
   - 在 generic not-found 前优先返回 `SCHEMA_MISMATCH`。
2. 修改 `test_error_handling.py`：
   - 补 schema object missing 分类测试。
   - 保留 vertex/edge target not found 测试。

验收命令：

```bash
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_error_handling.py -q
```

### Phase 3: FEATURE_DISABLED 文案

1. 修改 `server.py`：
   - 去掉 admin gate 和 table import 中误导性的 `V1` 文案。
   - `details` 增加更明确的启用条件。
2. 修改相关测试：
   - `test_v1_stable_tools.py`
   - `test_import_graph_data_tool.py`

验收命令：

```bash
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_v1_stable_tools.py hugegraph-mcp/tests/test_import_graph_data_tool.py -q
```

### Phase 4: README 和修复计划文档

1. 修改 `README.md`。
2. 修改 `README.zh-CN.md`。
3. 修改 `docs/graph_mcp_review_fix_plan.md`。

验收方式：

- 人工确认英文/中文 README 口径一致。
- 文档不再声明未通过的检查已经通过。

### Phase 5: 格式化

运行：

```bash
uv run --project hugegraph-mcp ruff format hugegraph-mcp/tests/test_manage_schema.py
```

要求：

- 只接受机械格式化变更。
- 不混入行为修改。

## 4. 最终验证命令

修复全部完成后按以下顺序验证：

```bash
uv run --project hugegraph-mcp ruff format --check hugegraph-mcp
uv run --project hugegraph-mcp ruff check hugegraph-mcp
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/test_error_handling.py hugegraph-mcp/tests/test_mutate_graph_properties_tool.py hugegraph-mcp/tests/test_v1_stable_tools.py hugegraph-mcp/tests/test_import_graph_data_tool.py hugegraph-mcp/tests/test_manage_schema.py -q
uv run --project hugegraph-mcp pytest hugegraph-mcp/tests -m "not live and not integration and not real_hugegraph and not llm"
RUN_MCP_REAL_HUGEGRAPH_TESTS=1 uv run --project hugegraph-mcp pytest hugegraph-mcp/tests/integration/test_real_write_path.py -vv
```

如果本地 HugeGraph Server 不可用，最后一条真实集成测试可以暂缓，但合入前必须补跑，并记录 HugeGraph Server 版本、图空间、图名和命令输出摘要。

## 5. 不在本轮处理的残余风险

- `mutate_graph_properties` 当前主要覆盖整键 append/eliminate 语义。若后续支持 `SET` / `LIST` cardinality 的元素级追加或移除，需要新增真实 HugeGraph 用例。
- edge id 编码已覆盖当前真实 composite id 路径，但仍建议保留真实 HugeGraph 回归，因为 composite edge id 格式可能随服务端版本或配置变化。
- `tests/test_v1_stable_tools.py` 当前通过 FastMCP 私有属性列工具，短期可接受；后续可考虑封装项目内测试 helper 或改用公开 API，降低对第三方内部实现的耦合。
