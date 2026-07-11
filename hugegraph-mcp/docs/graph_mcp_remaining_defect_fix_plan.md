# Graph MCP Remaining Defect Fix Plan

本文档记录 `graph-mcp` 分支在 2026-07-10 复核后确认的剩余缺陷及实施顺序。
计划基线为 `graph-mcp@32f4563`。本轮只制定计划，不修改实现。

## 1. 结论与边界

本服务按本地单用户部署设计，不在本轮引入 Bearer Token。无认证成立的前提是：

- 源码直启默认只监听 loopback。
- Docker 默认只向宿主机 loopback 发布端口。
- 用户显式监听非 loopback 地址时，启动日志必须给出安全告警，并由部署方提供前置认证或可信网络隔离。

Docker 容器内的进程仍监听 `0.0.0.0`，否则宿主机端口映射无法访问容器服务；安全边界由宿主机的 `127.0.0.1:8001:8001` 端口发布规则保证。

本轮计划修复六项问题：

| 优先级 | 问题 | 处理结论 |
| --- | --- | --- |
| High | HugeGraph-AI 源码直启默认监听 `0.0.0.0`，Docker 默认向所有宿主机接口发布 `8001` | 默认收紧到 loopback；非 loopback 显式启动告警；不增加应用内 Token |
| High | `HUGEGRAPH_MCP_READONLY` 非法值会被解析为 `False` | 严格解析，非法或空值按 `True` 处理并告警 |
| High | confirm nonce 在 TTL 内可重复使用 | 增加持久化、原子、单次消费的确认账本 |
| Medium | `SET` / `LIST` append 的预览和写后比较使用覆盖语义 | 按 property key cardinality 计算预览并比较 |
| Medium | edge page 查询允许 `vertex_id` 与 `page` 同时出现 | MCP 层提前返回 `VALIDATION_ERROR` |
| Low | 三个 client 纯内存合约测试被 integration 文件级 marker 覆盖 | 拆入 contract 测试文件，确保 unit/contract CI 收集 |

## 2. 已确定的技术方案

### 2.1 本地部署网络边界

涉及文件：

- `hugegraph-llm/src/hugegraph_llm/demo/rag_demo/app.py`
- `hugegraph-llm/src/tests/` 下新增或补充 CLI 配置测试
- `docker/docker-compose-network.yml`
- `docker/docker-compose-llm.yml`
- `hugegraph-llm/README.md`
- 根目录 `README.md`

实现要求：

1. 将 `app.py` 的 `--host` 默认值从 `0.0.0.0` 改为 `127.0.0.1`。
2. 抽取可测试的参数解析和 host 安全判断：`127.0.0.0/8`、`::1` 和 `localhost` 视为 loopback；`0.0.0.0`、`::`、局域网地址和其他主机名视为非 loopback。
3. 用户显式选择非 loopback host 时记录醒目的 warning，说明当前 HTTP API 没有统一认证，必须配置反向代理认证、防火墙或可信网络。
4. 保留 `docker/Dockerfile.llm` 和 `docker/Dockerfile.nk` 中容器内 `--host 0.0.0.0`。
5. 两个 Compose 文件都将 RAG 服务端口改为 `127.0.0.1:8001:8001`。
6. README 中的 `docker run` 示例改为 `-p 127.0.0.1:8001:8001`，并明确暴露到非 loopback 是部署方的显式安全选择。

验收标准：

- 不传 `--host` 时，传给 Uvicorn 的 host 是 `127.0.0.1`。
- 显式 `--host 0.0.0.0` 仍可启动，但产生安全告警。
- Compose 渲染结果中宿主机绑定地址为 `127.0.0.1`，容器目标端口仍为 `8001`。
- 文档不宣称服务已有 Bearer Token 或其他尚未实现的认证能力。

### 2.2 readonly 配置严格解析并 fail-closed

涉及文件：

- `hugegraph-mcp/hugegraph_mcp/config.py`
- `hugegraph-mcp/tests/test_config.py`
- `hugegraph-mcp/tests/test_readonly_mode.py`

实现要求：

1. 将布尔解析改为显式 true/false 集合，并接收变量名和安全默认值，不再用“不是 true 就是 false”的规则。
2. 建议接受：
   - true：`1`、`true`、`yes`、`on`，忽略大小写和首尾空格。
   - false：`0`、`false`、`no`、`off`，忽略大小写和首尾空格。
3. 解析器必须区分未设置（`None`）与显式空字符串：未设置时直接使用默认值且不告警；显式空字符串或非法值进入 fail-closed 分支并告警。
4. `HUGEGRAPH_MCP_READONLY` 未设置时保持默认 `True`；显式空字符串或非法值（如 `treu`、`junk`）也返回 `True`。
5. `HUGEGRAPH_MCP_ALLOW_AI` 和 `HUGEGRAPH_MCP_ADMIN_MODE` 使用同一严格解析器，但非法值保持各自安全默认值 `False`。
6. warning 只包含变量名，不回显非法原始值，更不能输出密码、Token 或其他配置内容。

验收标准：

- `HUGEGRAPH_MCP_READONLY=treu`、`junk`、空字符串均不能开启写权限。
- 合法 false 值仍能显式关闭 readonly。
- 非法 `ALLOW_AI` / `ADMIN_MODE` 值不能开启对应能力。
- 环境变量变化后的配置缓存行为保持正确。

### 2.3 confirm nonce 持久化单次消费

涉及文件：

- `hugegraph-mcp/hugegraph_mcp/plan_hash.py`
- `hugegraph-mcp/hugegraph_mcp/config.py`
- 建议新增 `hugegraph-mcp/hugegraph_mcp/confirmation_store.py`
- `hugegraph-mcp/hugegraph_mcp/confirmable_workflow.py`
- `hugegraph-mcp/hugegraph_mcp/envelope.py`
- 四个调用 `verify_plan_hash()` 的写入口：
  - `tools/manage_schema.py`
  - `tools/manage_graph_data.py`
  - `tools/ingest_graph_data.py`
  - `tools/mutate_graph_properties.py`
- `hugegraph-mcp/tests/test_plan_hash.py`
- 四个写入口的定向测试
- `hugegraph-mcp/docs/p0a-integration-checklist.md`

采用持久化单次消费，而不是仅使用进程内 `set`。原因是进程重启和多个本地 worker 都不能重新放开同一确认请求。

实现要求：

1. 使用 Python 标准库 SQLite 建立本地确认账本，不引入外部服务或第三方依赖。
2. 账本只保存 `nonce_digest=SHA-256(nonce)`、`plan_hash`、`expires_at`、`consumed_at` 等非敏感摘要，不保存原始 nonce、payload、凭据或图数据。`nonce_digest` 是全局唯一键且不绑定 payload；复用同一 nonce 生成不同工具或 payload 的计划也必须被拒绝。
3. 状态目录通过 `HUGEGRAPH_MCP_STATE_DIR` 配置；默认使用 `$XDG_STATE_HOME/hugegraph-mcp`，未设置 XDG 时使用 `~/.local/state/hugegraph-mcp`。目录权限为 `0700`，数据库文件权限为 `0600`；不支持 POSIX 权限的平台做能力范围内的最严格处理。
4. 先完成 plan hash、TTL、目标、schema 和 readonly 校验，再以 `nonce_digest` 为唯一键插入原子消费记录；只有插入成功的请求可以进入真实写入。
5. 消费发生在第一个副作用之前。写入超时、失败或部分成功后，同一 plan 不允许重试；调用方必须检查目标状态并重新 dry-run。
6. 并发提交相同确认时只能有一个调用获得执行权。
7. 过期记录可在消费时惰性清理；清理失败不能影响当前合法请求，但确认账本不可用或无法持久化时必须 fail-closed，禁止写入。
8. 新增明确错误类型 `PLAN_ALREADY_USED`。响应不得泄露账本路径或内部 SQL 错误。
9. 保留 `verify_plan_hash()` 作为无副作用的纯校验函数，新增统一的 `verify_and_consume_plan()` 供所有真实写入口调用，避免单元测试或预检查意外消费计划。

验收标准：

- 第一次合法 confirm 可执行，第二次相同 confirm 返回 `PLAN_ALREADY_USED`，且没有第二次写调用。
- 两个并发相同 confirm 只有一个成功进入执行函数。
- 服务重新创建 store 实例后，相同 plan 仍被拒绝。
- 过期、hash 不匹配和 readonly 请求不会占用 nonce。
- 执行失败或 `PARTIAL_APPLY` 后相同 plan 仍被拒绝，并提示重新查询和 dry-run。
- 所有四个真实写入口使用同一消费路径，不能存在绕过入口。

### 2.4 集合属性 append 预览和写后校验

涉及文件：

- `hugegraph-mcp/hugegraph_mcp/tools/mutate_graph_properties.py`
- `hugegraph-mcp/hugegraph_mcp/tools/schema_utils.py`（如抽取共享 cardinality helper）
- `hugegraph-mcp/tests/test_mutate_graph_properties_tool.py`
- `hugegraph-mcp/tests/integration/test_real_write_path.py`

实现要求：

1. 从 live schema 的 `propertykeys` 建立 `property name -> cardinality` 映射，兼容当前 schema 包装格式和字段别名。
2. `_preview_mutation()` 必须接收 cardinality 信息：
   - `SINGLE`：append 后使用新值，保持当前替换语义。
   - `LIST`：按原顺序拼接新值，保留重复项。
   - `SET`：按首次出现顺序合并并去重，使预览稳定；写后比较忽略顺序。
3. `LIST` / `SET` 属性的 append 输入必须是集合值；不符合 schema cardinality 的输入在写前返回 `VALIDATION_ERROR`。
4. `eliminate` 继续表示删除整个 property key，不改为按集合元素删除。
5. 写后 `_properties_match()` 使用同一 cardinality 规则：`SET` 比较集合等价性，`LIST` 比较顺序和重复项，`SINGLE` 直接比较。
6. `plan_hash` 继续绑定 schema hash，因此 dry-run 后 cardinality 改变时 confirm 必须失效。

验收标准：

- `LIST [a] + [b, b]` 的预览和写后期望为 `[a, b, b]`。
- `SET [a] + [b, a]` 的预览不重复；服务端以不同顺序返回时仍验证成功。
- `SINGLE old + new` 仍预览为 `new`。
- 集合属性传入标量时不执行任何写调用。
- 使用真实 HugeGraph 1.7.0 覆盖 vertex 和 edge 至少各一条集合 append 路径，避免仅凭 fake manager 证明语义。

### 2.5 拒绝非法 edge 分页参数组合

涉及文件：

- `hugegraph-mcp/hugegraph_mcp/tools/query_graph_data.py`
- `hugegraph-mcp/tests/test_query_graph_data_tool.py`

实现要求：

1. 当 `target="edge"`、`operation="page"` 且同时提供 `vertex_id` 与非空 `page` 时，在创建 client 或发 REST 请求前返回 `VALIDATION_ERROR`。
2. 错误 suggestion 明确给出两种合法方式：
   - 按顶点查询：传 `vertex_id` 和 `direction`，不传 `page`。
   - 普通分页：传 `page`，不传 `vertex_id`。
3. 保留已有规则：提供 `vertex_id` 时必须提供合法 `direction`。
4. 将当前允许 `vertex_id + direction + page` 成功的测试改为负向回归测试，并分别增加两个合法分支测试。

验收标准：

- 非法组合返回 `VALIDATION_ERROR`，fake graph manager 的调用列表为空。
- `vertex_id + direction` 和普通 `page` 查询仍按原 client 参数顺序执行。
- vertex 分页行为不受影响。

### 2.6 修正 client 测试 marker

涉及文件：

- `hugegraph-python-client/src/tests/api/test_schema.py`
- 建议新增 `hugegraph-python-client/src/tests/api/test_schema_contract.py`

实现要求：

1. 将以下三个不访问 HugeGraph 的测试及 `DummySchemaSession` 移到独立 contract 文件：
   - property key payload 包含 `aggregate_type`。
   - property key payload 包含 `user_data`。
   - index label 字段保持顺序并去重。
2. 新文件使用 `pytestmark = pytest.mark.contract`；原 `test_schema.py` 保持 `integration + hugegraph` 文件级 marker。
3. 只移动测试归属，不重复同一测试，也不降低真实 schema integration 覆盖。

验收标准：

- `pytest --collect-only -m "unit or contract"` 能收集这三个测试。
- `pytest --collect-only -m "integration and hugegraph"` 仍收集 `TestSchemaManager`，但不收集三个纯内存测试。

## 3. 实施任务与依赖

- [ ] 1. **建立修复前基线** `[优先级: 高]`
  - [ ] 1.1. 记录分支 HEAD、工作区状态和现有自动测试结果，保留用户未跟踪文件。
  - [ ] 1.2. 为六项缺陷先补充可失败的定向测试，确认测试能命中真实缺陷。 `(依赖于: 1.1)`

- [ ] 2. **收紧本地部署网络边界** `[优先级: 高]`
  - [ ] 2.1. 增加默认 host 和非 loopback 告警测试。 `(依赖于: 1.2)`
  - [ ] 2.2. 修改源码启动默认值并实现告警。 `(依赖于: 2.1)`
  - [ ] 2.3. 修改 Compose 端口发布和 README 示例，保留容器内 `0.0.0.0`。 `(依赖于: 2.2)`

- [ ] 3. **修复写安全配置和确认重放** `[优先级: 高]`
  - [ ] 3.1. 实现布尔严格解析和 readonly fail-closed。 `(依赖于: 1.2)`
  - [ ] 3.2. 实现 SQLite 确认账本、`PLAN_ALREADY_USED` 和原子消费测试。 `(依赖于: 1.2)`
  - [ ] 3.3. 将四个真实写入口迁移到统一 verify-and-consume 流程。 `(依赖于: 3.2)`
  - [ ] 3.4. 补充失败、部分成功、并发和进程重建后的重放测试。 `(依赖于: 3.3)`

- [ ] 4. **修复 MCP 数据语义** `[优先级: 中]`
  - [ ] 4.1. 实现 cardinality-aware 属性预览、输入校验和写后比较。 `(依赖于: 1.2)`
  - [ ] 4.2. 补 `SINGLE`、`LIST`、`SET`、vertex、edge 的单元与真实服务测试。 `(依赖于: 4.1)`
  - [ ] 4.3. 增加 edge `vertex_id + page` 参数互斥校验并补合法分支测试。 `(依赖于: 1.2)`

- [ ] 5. **修正 client 测试分层** `[优先级: 低]`
  - [ ] 5.1. 将三个纯内存 schema 测试移动到 contract 文件。 `(依赖于: 1.1)`
  - [ ] 5.2. 用 collect-only 命令验证两个 CI marker 集合互不串层。 `(依赖于: 5.1)`

- [ ] 6. **完成回归与文档同步** `[优先级: 高]`
  - [ ] 6.1. 运行格式、lint、MCP 非外部测试和 client unit/contract 测试。 `(依赖于: 2.3, 3.4, 4.3, 5.2)`
  - [ ] 6.2. 使用 HugeGraph 1.7.0 运行 MCP 真实写入和 client integration 测试。 `(依赖于: 6.1)`
  - [ ] 6.3. 更新错误类型和本地部署边界文档，只记录实际执行过的验证结果。 `(依赖于: 6.2)`

## 4. 验证矩阵

定向测试通过后，再执行完整门禁。建议命令如下：

```bash
# Workspace format and lint
uv run ruff format --check .
uv run ruff check .
uv run ty check hugegraph-llm/src hugegraph-python-client/src

# Docker host-port rendering
docker compose -f docker/docker-compose-network.yml config
docker compose -f docker/docker-compose-llm.yml config

# HugeGraph-AI API / CLI affected tests
uv run pytest hugegraph-llm/src/tests -m "not integration and not hugegraph and not smoke and not external" -q

# MCP unit/contract tests
cd hugegraph-mcp
uv run pytest -m "not live and not integration and not llm" -q

# Client unit/contract tests and marker collection
cd ..
uv run pytest hugegraph-python-client/src/tests -m "unit or contract" -q
uv run pytest hugegraph-python-client/src/tests --collect-only -m "unit or contract" -q
uv run pytest hugegraph-python-client/src/tests --collect-only -m "integration and hugegraph" -q
```

真实 HugeGraph 验证必须在 HugeGraph 1.7.0 可用时执行：

```bash
cd hugegraph-mcp
HUGEGRAPH_URL=http://127.0.0.1:8080 \
HUGEGRAPH_GRAPH_PATH=DEFAULT/hugegraph \
HUGEGRAPH_USER=admin \
HUGEGRAPH_PASSWORD=admin \
uv run pytest tests/integration/test_real_write_path.py -m real_hugegraph -q

cd ..
HUGEGRAPH_URL=http://127.0.0.1:8080 \
HUGEGRAPH_GRAPHSPACE=DEFAULT \
HUGEGRAPH_GRAPH=hugegraph \
HUGEGRAPH_USER=admin \
HUGEGRAPH_PASSWORD=admin \
uv run pytest hugegraph-python-client/src/tests -m "integration and hugegraph" -q
```

## 5. 完成门禁

只有同时满足以下条件，才可把本轮六项问题标记为已修复：

- 源码启动和 Docker 默认都只从宿主机 loopback 暴露 RAG HTTP 服务。
- readonly 非法配置经过自动测试证明会 fail-closed。
- 所有确认式写入口都经过持久化单次消费，且并发与重启场景有测试。
- 集合 append 在真实 HugeGraph 上验证，不再出现错误 `PARTIAL_APPLY`。
- 非法 edge 分页组合在 MCP 边界被拒绝。
- 三个 client 合约测试进入 unit/contract CI 收集集合。
- `ruff`、`ty`、Compose 渲染、MCP 非外部测试、client unit/contract 测试和 HugeGraph 真实集成测试均通过。

如果真实 HugeGraph 服务不可用，只能将状态记录为“代码和单元测试已完成，真实集成待验证”，不能声明全部修复完成。
