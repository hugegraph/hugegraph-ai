# HugeGraph MCP Server 需求文档

## 简介

HugeGraph MCP Server 是一个基于 Model Context Protocol (MCP) 的服务实现,旨在为大语言模型(LLM)提供与 HugeGraph 图数据库的标准化交互接口。该服务使 Claude Desktop 等 MCP 客户端能够通过自然语言操作 HugeGraph 数据库,执行图数据的 CRUD 操作、Schema 管理、图算法调用等功能。

本实现将参考 Neo4j MCP 和 NebulaGraph MCP 的设计,采用 Python 语言开发,集成到现有的 hugegraph-llm 项目中,复用现有的 PyHugeClient 和相关工具链。

## 需求列表

### 需求 1: 项目基础设施

**用户故事:** 作为开发者,我希望能够快速安装和配置 HugeGraph MCP Server,以便在不同环境中使用。

#### 验收标准

1. WHEN 用户通过 `uvx hugegraph-mcp-server` 命令启动 THEN 系统应成功加载配置并启动 MCP 服务
2. WHEN 用户提供环境变量(HUGEGRAPH_URL, HUGEGRAPH_GRAPH, HUGEGRAPH_USER, HUGEGRAPH_PASSWORD) THEN 系统应使用这些配置连接到 HugeGraph
3. WHEN 用户提供 .env 文件配置 THEN 系统应优先从 .env 文件读取配置信息
4. WHEN 用户未提供配置 THEN 系统应从现有的 hugegraph_llm.config.huge_settings 中读取默认配置
5. WHEN 用户指定 `--transport stdio` 参数 THEN 系统应以 STDIO 模式启动
6. WHEN 用户指定 `--transport http` 参数 THEN 系统应以 HTTP 模式启动,并支持 --host 和 --port 参数
7. WHEN 启动失败(如连接不上 HugeGraph) THEN 系统应返回清晰的错误信息并退出

### 需求 2: 顶点(Vertex)的 CRUD 操作

**用户故事:** 作为 LLM 用户,我希望能够通过自然语言创建、查询、更新和删除图中的顶点,以便管理图数据。

#### 验收标准

1. WHEN LLM 调用 `get_vertex` 工具并提供顶点 ID THEN 系统应返回该顶点的完整信息(包括 label 和所有 properties)
2. WHEN LLM 调用 `get_vertices` 工具并提供多个顶点 ID THEN 系统应批量返回这些顶点的信息
3. WHEN LLM 调用 `query_vertices` 工具并提供查询条件(label, property filters) THEN 系统应返回符合条件的顶点列表
4. WHEN 查询顶点的结果超过默认限制(如 100 个) THEN 系统应自动分页并返回前 N 个结果及提示信息
5. WHEN LLM 调用 `create_vertex` 工具并提供 label 和 properties THEN 系统应创建新顶点并返回顶点 ID
6. WHEN LLM 调用 `create_vertices` 工具并提供顶点列表 THEN 系统应批量创建顶点并返回成功/失败的详细结果
7. WHEN 创建顶点时 label 不存在于 schema 中 THEN 系统应返回错误信息,提示 label 不存在
8. WHEN 创建顶点时 properties 类型与 schema 定义不匹配 THEN 系统应返回验证错误并说明期望的类型
9. WHEN LLM 调用 `update_vertex` 工具并提供顶点 ID 和新的 properties THEN 系统应更新顶点属性并返回更新后的顶点信息
10. WHEN 更新顶点时提供的 property key 不存在于 schema THEN 系统应返回错误信息
11. WHEN LLM 调用 `delete_vertex` 工具并提供顶点 ID THEN 系统应删除该顶点及其所有关联的边,并返回删除确认
12. WHEN 删除的顶点不存在 THEN 系统应返回 404 错误信息

### 需求 3: 边(Edge)的 CRUD 操作

**用户故事:** 作为 LLM 用户,我希望能够通过自然语言创建、查询和更新图中的边,以便建立和管理实体之间的关系。

#### 验收标准

1. WHEN LLM 调用 `get_edge` 工具并提供边 ID THEN 系统应返回该边的完整信息(包括 label, source, target 和 properties)
2. WHEN LLM 调用 `get_edges` 工具并提供多个边 ID THEN 系统应批量返回这些边的信息
3. WHEN LLM 调用 `query_edges` 工具并提供查询条件(label, source_id, target_id, property filters) THEN 系统应返回符合条件的边列表
4. WHEN 查询边时仅提供 source_id THEN 系统应返回该顶点的所有出边
5. WHEN 查询边时仅提供 target_id THEN 系统应返回该顶点的所有入边
6. WHEN LLM 调用 `create_edge` 工具并提供 label, source_id, target_id 和 properties THEN 系统应创建新边并返回边 ID
7. WHEN LLM 调用 `create_edges` 工具并提供边列表 THEN 系统应批量创建边并返回成功/失败的详细结果
8. WHEN 创建边时 source 或 target 顶点不存在 THEN 系统应返回错误信息,提示顶点不存在
9. WHEN 创建边时 label 与 source/target 顶点的 label 组合不符合 schema 定义 THEN 系统应返回错误信息
10. WHEN LLM 调用 `update_edge` 工具并提供边 ID 和新的 properties THEN 系统应更新边属性并返回更新后的边信息
11. WHEN 批量创建边时部分成功部分失败 THEN 系统应返回成功的边 ID 列表和失败的错误详情

### 需求 4: Schema 管理

**用户故事:** 作为 LLM 用户,我希望能够查询和理解图数据库的 Schema 结构,以便正确地创建和查询数据。

#### 验收标准

1. WHEN LLM 调用 `get_schema` 工具 THEN 系统应返回完整的 schema 信息(包括 vertexlabels, edgelabels, propertykeys)
2. WHEN LLM 通过 MCP Resource 访问 `hugegraph://schema` THEN 系统应返回简化的 schema 信息(仅包含必要字段)
3. WHEN LLM 调用 `get_vertex_labels` 工具 THEN 系统应返回所有顶点 label 及其属性定义
4. WHEN LLM 调用 `get_edge_labels` 工具 THEN 系统应返回所有边 label 及其属性定义和约束(source_label, target_label)
5. WHEN schema 为空(新图) THEN 系统应返回空的 schema 结构并提示用户需要先定义 schema
6. WHEN LLM 请求 schema 的统计信息 THEN 系统应返回 vertex label 数量、edge label 数量和 property key 数量

### 需求 5: 图统计信息

**用户故事:** 作为 LLM 用户,我希望能够获取图数据库的统计信息,以便了解数据规模和概况。

#### 验收标准

1. WHEN LLM 通过 MCP Resource 访问 `hugegraph://statistics` THEN 系统应返回图的统计信息
2. WHEN 获取统计信息 THEN 系统应返回顶点总数、边总数
3. WHEN 获取统计信息 THEN 系统应返回最多 10000 个顶点 ID 的样本列表
4. WHEN 获取统计信息 THEN 系统应返回最多 200 个边 ID 的样本列表
5. WHEN 返回样本数据时数据量超过限制 THEN 系统应在返回结果中包含说明信息,告知这只是部分数据

### 需求 6: 自然语言转 Gremlin 查询支持

**用户故事:** 作为 LLM 用户,我希望能够获取 text2gremlin 的 prompt 模板,以便 LLM 能够基于这些信息将自然语言转换为 Gremlin 查询。

#### 验收标准

1. WHEN LLM 通过 MCP Resource 访问 `hugegraph://text2gremlin-prompt` THEN 系统应返回 text2gremlin 的 prompt 模板(包含 Gremlin 语法说明和示例)
2. WHEN LLM 调用 `get_text2gremlin_prompt` 工具 THEN 系统应返回完整的 text2gremlin prompt 模板
3. WHEN LLM 通过 MCP Resource 访问 `hugegraph://gremlin-examples` THEN 系统应返回预定义的 Gremlin 查询示例
4. WHEN 调用 `get_text2gremlin_prompt` 工具时 THEN 系统不应调用任何外部 LLM API,仅返回 prompt 文本
5. WHEN 返回 text2gremlin prompt THEN 系统应提供通用的 Gremlin 语法说明和查询示例,不包含特定图的 schema 信息

### 需求 7: 图算法支持

**用户故事:** 作为 LLM 用户,我希望能够快速调用常用的图算法,以便分析图结构和关系。

#### 验收标准

1. WHEN LLM 调用 `shortest_path` 工具并提供起始顶点 ID 和目标顶点 ID THEN 系统应返回最短路径(包括路径上的顶点和边)
2. WHEN 两个顶点之间不存在路径 THEN 系统应返回空路径并说明原因
3. WHEN LLM 调用 `k_neighbor` 工具并提供顶点 ID 和深度 k THEN 系统应返回 k 度邻居的所有顶点
4. WHEN k 值过大(如 >5) THEN 系统应限制最大深度并返回警告信息
5. WHEN k 度邻居查询结果数量过多 THEN 系统应限制返回数量(如最多 1000 个)并提示
6. WHEN 调用图算法时提供的顶点 ID 不存在 THEN 系统应返回错误信息

### 需求 8: 错误处理和验证

**用户故事:** 作为开发者和用户,我希望系统能够提供清晰的错误信息和输入验证,以便快速定位和解决问题。

#### 验收标准

1. WHEN 任何操作失败 THEN 系统应返回详细的错误信息(包括错误类型、原因、建议)
2. WHEN 连接 HugeGraph 失败 THEN 系统应返回连接错误并提示检查配置
3. WHEN 输入参数缺失或类型错误 THEN 系统应在执行前验证并返回参数验证错误
4. WHEN 批量操作部分成功 THEN 系统应返回成功列表和失败列表,每个失败项包含详细错误信息
5. WHEN 创建或更新操作违反 schema 约束 THEN 系统应返回约束违反错误并说明具体的约束要求
6. WHEN 顶点或边 ID 格式错误 THEN 系统应返回格式错误信息
7. WHEN 操作超时 THEN 系统应返回超时错误并建议优化查询或增加超时时间

### 需求 9: MCP 协议规范

**用户故事:** 作为 MCP 客户端,我希望 HugeGraph MCP Server 完全遵循 MCP 协议规范,以便能够无缝集成。

#### 验收标准

1. WHEN MCP 客户端发送 `initialize` 请求 THEN 服务器应返回服务器信息和支持的协议版本
2. WHEN MCP 客户端请求 `tools/list` THEN 服务器应返回所有可用的工具列表及其描述
3. WHEN MCP 客户端请求 `resources/list` THEN 服务器应返回所有可用的资源列表(schema, statistics, gremlin-examples, text2gremlin-prompt)
4. WHEN MCP 客户端调用 `tools/call` 并提供工具名称和参数 THEN 服务器应执行工具并返回结构化结果
5. WHEN MCP 客户端请求 `resources/read` 并提供资源 URI THEN 服务器应返回对应的资源内容
6. WHEN 工具调用失败 THEN 服务器应返回符合 MCP 规范的错误响应
7. WHEN 以 STDIO 模式运行 THEN 服务器应通过标准输入输出进行 JSON-RPC 通信
8. WHEN 以 HTTP 模式运行 THEN 服务器应支持 HTTP POST 请求和 Server-Sent Events (SSE)

### 需求 10: 配置和部署

**用户故事:** 作为系统管理员,我希望能够灵活配置和部署 HugeGraph MCP Server,以便适应不同的环境需求。

#### 验收标准

1. WHEN 用户设置环境变量 HUGEGRAPH_URL THEN 系统应使用该 URL 连接 HugeGraph
2. WHEN 用户设置环境变量 HUGEGRAPH_GRAPH THEN 系统应连接到指定的图实例
3. WHEN 用户设置环境变量 HUGEGRAPH_USER 和 HUGEGRAPH_PASSWORD THEN 系统应使用这些凭据进行认证
4. WHEN 用户设置环境变量 HUGEGRAPH_GRAPHSPACE THEN 系统应在指定的 graphspace 中操作
5. WHEN .env 文件存在 THEN 系统应自动加载 .env 文件中的配置
6. WHEN 环境变量和 .env 文件都存在 THEN 环境变量应优先级更高
7. WHEN 未提供任何配置 THEN 系统应尝试从 hugegraph_llm.config.huge_settings 读取默认配置
8. WHEN 用户指定 --log-level 参数 THEN 系统应设置对应的日志级别(DEBUG, INFO, WARNING, ERROR)

### 需求 11: 测试和质量保证

**用户故事:** 作为开发者,我希望项目包含完善的测试,以便保证代码质量和功能正确性。

#### 验收标准

1. WHEN 运行单元测试 THEN 所有 MCP 工具的核心逻辑应通过单元测试(使用 mock)
2. WHEN 运行集成测试 THEN 系统应能够连接真实的 HugeGraph 实例并执行端到端测试
3. WHEN 使用 @modelcontextprotocol/inspector 工具 THEN 应能够成功连接并测试所有工具
4. WHEN 执行测试时 THEN 测试覆盖率应达到核心功能代码的 80% 以上
5. WHEN 测试失败 THEN 应输出清晰的失败原因和堆栈信息

### 需求 12: 文档和示例

**用户故事:** 作为新用户,我希望能够通过清晰的文档快速了解和使用 HugeGraph MCP Server。

#### 验收标准

1. WHEN 用户查看 README.md THEN 应包含项目简介、安装方法、配置说明和快速开始示例
2. WHEN 用户查看 README.md THEN 应包含每个 MCP 工具的简要说明和使用示例
3. WHEN 用户查看 API 文档 THEN 应包含每个工具的详细参数说明、返回值格式和错误码
4. WHEN 用户查看集成指南 THEN 应包含如何在 Claude Desktop 中配置 HugeGraph MCP Server 的步骤
5. WHEN 用户查看集成指南 THEN 应包含在其他 MCP 客户端(如 Cursor, VS Code)中的配置示例
6. WHEN 用户查看示例代码 THEN 应包含常见使用场景的完整示例(创建知识图谱、查询关系等)
