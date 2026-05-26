# 需求文档: HugeGraph MCP 用户主功能收敛

## 1. 介绍

本需求文档定义 HugeGraph MCP 面向用户的主功能收敛方案。当前 MCP 已具备查询 schema、执行 Gremlin、管理 schema、调用 HugeGraph-AI 等底层能力，但用户入口较分散，存在多个功能重叠、自然语言链路不稳定、底层调试入口容易被误用的问题。

本次收敛的目标是把用户可见能力整理为四个主功能：

1. 查看图状态和 schema。
2. 查询图。
3. 设计和管理 schema。
4. 通过自然语言或结构化 SQL 表导入图数据。

系统应保留必要的底层调试能力，但默认用户体验应围绕上述四个主功能组织。所有涉及写入、schema 修改、索引刷新或导入的操作都必须经过权限保护、校验、dry-run、确认和可追溯输出，避免 agent 或用户误操作真实图数据。

本阶段不要求实现完整外部数据库直连、不要求删除 schema、不要求自动回滚，也不要求将所有 HugeGraph-AI Web Demo 能力一次性暴露给 MCP。结构化 SQL 表导入的初始范围应优先支持 SQL 查询结果、CSV/JSON 表格或等价的结构化行列数据，再根据后续设计决定是否加入数据库连接器。

## 2. 需求列表

### 2.1 用户入口收敛

- **用户故事**: 作为一名 **Agent 用户**, 我希望 **只看到少量清晰的主功能入口**, 以便 **不用理解底层工具差异也能完成图数据库查询、建模和导入任务**。
- **验收标准 (EARS 格式)**:
  - **U1**: The **HugeGraph MCP** shall **将普通用户主路径收敛为“查看图状态和 schema”“查询图”“设计和管理 schema”“导入图数据”四类能力**。
  - **U2**: The **HugeGraph MCP** shall **在用户文档和工具描述中优先说明四类主能力，而不是优先暴露底层调试入口**。
  - **E1**: WHEN **用户需要查看当前图是否可用**, the **HugeGraph MCP** shall **引导用户使用“查看图状态和 schema”能力**。
  - **E2**: WHEN **用户需要回答图相关问题**, the **HugeGraph MCP** shall **引导用户使用“查询图”能力**。
  - **E3**: WHEN **用户需要创建或变更 schema**, the **HugeGraph MCP** shall **引导用户使用“设计和管理 schema”能力**。
  - **E4**: WHEN **用户需要把文本或表格数据写入图**, the **HugeGraph MCP** shall **引导用户使用“导入图数据”能力**。
  - **X1**: IF **用户尝试直接使用底层写入或底层 schema 调试能力完成普通业务流程**, THEN the **HugeGraph MCP** shall **返回风险提示，并建议改用对应主功能流程**。

### 2.2 查看图状态和 schema

- **用户故事**: 作为一名 **Agent 用户**, 我希望 **在操作前快速了解当前图、schema、服务状态和权限状态**, 以便 **决定下一步是查询、建模还是导入数据**。
- **验收标准 (EARS 格式)**:
  - **E5**: WHEN **用户请求查看图状态**, the **HugeGraph MCP** shall **返回当前 graph、graphspace、HugeGraph Server 连通状态、readonly 状态和 schema 摘要**。
  - **E6**: WHEN **用户请求查看完整 schema**, the **HugeGraph MCP** shall **返回 property keys、vertex labels、edge labels、主键、属性、索引和边端点约束**。
  - **E7**: WHEN **HugeGraph Server 可用且统计查询成功**, the **HugeGraph MCP** shall **返回顶点数量和边数量**。
  - **X2**: IF **顶点数量或边数量统计失败**, THEN the **HugeGraph MCP** shall **保留其他状态信息，并在 warnings 中说明统计失败原因或降级结果**。
  - **E8**: WHEN **HugeGraph-AI 服务可访问**, the **HugeGraph MCP** shall **返回自然语言查询、文本抽图和向量索引相关能力的可用状态**。
  - **X3**: IF **HugeGraph-AI 的健康检查路径不存在但服务根路径或 OpenAPI 可访问**, THEN the **HugeGraph MCP** shall **不得仅因健康检查路径 404 就判定 AI 服务完全不可用**。
  - **O1**: WHERE **用户请求包含完整 schema**, the **HugeGraph MCP** shall **在输出中同时包含适合 agent 使用的简化 schema 和可审计的原始 schema**。

### 2.3 查询图

- **用户故事**: 作为一名 **业务用户或 Agent 用户**, 我希望 **用自然语言、只读查询语句或查询草稿来查询图**, 以便 **快速获得图中的答案、证据或可复查的查询逻辑**。
- **验收标准 (EARS 格式)**:
  - **E9**: WHEN **用户输入自然语言问题**, the **HugeGraph MCP** shall **优先通过自然语言图查询链路返回答案**。
  - **E10**: WHEN **自然语言图查询返回答案**, the **HugeGraph MCP** shall **返回答案、命中的关键实体、相关关系或证据摘要**。
  - **E11**: WHEN **用户要求查看证据**, the **HugeGraph MCP** shall **返回可追溯的图结果、命中顶点、命中边或查询依据**。
  - **E12**: WHEN **用户输入只读图查询语句**, the **HugeGraph MCP** shall **执行该查询并返回结构化结果**。
  - **E13**: WHEN **用户要求从自然语言生成查询语句**, the **HugeGraph MCP** shall **默认只生成查询草稿，不自动执行**。
  - **E14**: WHEN **用户要求生成并执行查询语句**, the **HugeGraph MCP** shall **仅在安全判定为只读时执行**。
  - **X4**: IF **查询语句包含新增、修改、删除、schema 修改或其他写风险**, THEN the **HugeGraph MCP** shall **拒绝执行并返回结构化安全错误**。
  - **X5**: IF **自然语言图查询链路不可用或返回空结果**, THEN the **HugeGraph MCP** shall **返回明确原因、降级建议和下一步动作，例如改用只读查询语句或生成查询草稿**。
  - **U3**: The **HugeGraph MCP** shall **把自然语言查询、查询语句生成和只读查询执行组织为同一个“查询图”用户能力，而不是让普通用户理解多个底层入口**。
  - **U4**: The **HugeGraph MCP** shall **兼容 HugeGraph-AI 返回的不同答案字段，并统一映射为用户可读答案和证据**。
  - **U12**: The **HugeGraph MCP** shall **对用户提交或 AI 生成的 Gremlin 查询采用默认拒绝的安全判定策略，只有被明确判定为只读的查询才允许执行**。
  - **E38**: WHEN **Gremlin 查询被提交到只读执行入口**, the **HugeGraph MCP** shall **通过语法解析、AST/遍历步骤分类或等价的 allowlist 机制确认其仅包含允许的只读 traversal 步骤后再执行**。
  - **X19**: IF **Gremlin 查询包含 mutation 步骤、side-effect 步骤、lambda/script 执行、schema 操作、远程代码执行模式，或无法被可靠判定为只读**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 `UNSAFE_GREMLIN`**。
  - **S4**: WHILE **后端 HugeGraph Server 提供 readonly 或等价写保护能力**, the **HugeGraph MCP** shall **仍然在请求发送到后端前执行自身的 Gremlin 只读安全判定**。

### 2.4 设计和管理 schema

- **用户故事**: 作为一名 **图建模用户**, 我希望 **通过一个安全流程设计、校验和应用 schema**, 以便 **在不误改生产图的前提下完成图模型演进**。
- **验收标准 (EARS 格式)**:
  - **E15**: WHEN **用户描述业务场景但未给出完整 schema**, the **HugeGraph MCP** shall **引导用户形成候选点类型、边类型、属性、主键和索引设计**。
  - **E16**: WHEN **用户提交 schema 操作计划**, the **HugeGraph MCP** shall **先校验属性、点类型、边类型、主键、边端点、索引和重复定义**。
  - **E17**: WHEN **用户请求 dry-run schema 变更**, the **HugeGraph MCP** shall **返回将创建或修改的 schema 操作列表、风险提示和计划校验码**。
  - **E18**: WHEN **用户确认应用 schema 变更**, the **HugeGraph MCP** shall **校验确认标记和计划校验码后再执行变更**。
  - **S1**: WHILE **MCP 处于 readonly 模式**, the **HugeGraph MCP** shall **拒绝所有 schema 写入和 schema apply 操作**。
  - **X6**: IF **schema 操作计划包含删除 schema**, THEN the **HugeGraph MCP** shall **拒绝执行并说明当前版本不支持删除 schema**。
  - **X7**: IF **确认执行时的计划校验码与 dry-run 结果不一致**, THEN the **HugeGraph MCP** shall **拒绝执行并要求重新 dry-run**。
  - **U5**: The **HugeGraph MCP** shall **将底层 schema 调试能力标记为高级能力，并在普通用户主路径中优先使用统一 schema 管理流程**。

### 2.5 自然语言导入图数据

- **用户故事**: 作为一名 **知识图谱构建用户**, 我希望 **从自然语言文本中抽取候选点边并安全导入 HugeGraph**, 以便 **把非结构化知识转成可查询的图数据**。
- **验收标准 (EARS 格式)**:
  - **E19**: WHEN **用户提交自然语言文本并请求抽图**, the **HugeGraph MCP** shall **返回候选顶点、候选边、属性和 schema 参考信息，且不直接写入图数据库**。
  - **E20**: WHEN **抽取结果包含 schema 中不存在的 label 或属性**, the **HugeGraph MCP** shall **返回 schema warning 或 schema mismatch 信息**。
  - **E21**: WHEN **用户请求导入抽取结果**, the **HugeGraph MCP** shall **先基于 live schema 校验顶点主键、属性类型、边类型和边端点可解析性**。
  - **E22**: WHEN **用户请求 dry-run 导入**, the **HugeGraph MCP** shall **返回预计写入顶点数、边数、风险、warnings 和计划校验码，且不产生写入**。
  - **E23**: WHEN **用户确认导入**, the **HugeGraph MCP** shall **仅在非 readonly、确认标记有效、计划校验码匹配且 schema 校验通过时执行写入**。
  - **E24**: WHEN **导入成功**, the **HugeGraph MCP** shall **返回批次标识、写入摘要和后续是否需要刷新向量索引的建议**。
  - **X8**: IF **payload 缺少 live schema 要求的顶点主键**, THEN the **HugeGraph MCP** shall **拒绝导入并指出缺失的 label 和主键字段**。
  - **X9**: IF **边的 source 或 target 无法解析到 payload 中已有顶点或图中允许的目标**, THEN the **HugeGraph MCP** shall **拒绝导入并指出无法解析的端点**。
  - **S2**: WHILE **MCP 处于 readonly 模式**, the **HugeGraph MCP** shall **允许抽取和 dry-run，但拒绝实际写入**。

### 2.6 结构化 SQL 表或表格数据导入图数据

- **用户故事**: 作为一名 **数据集成用户**, 我希望 **把 SQL 查询结果或结构化表格数据映射成图数据并安全导入**, 以便 **将关系型或行列式数据转成 HugeGraph 中的点和边**。
- **验收标准 (EARS 格式)**:
  - **E25**: WHEN **用户提交结构化表格数据**, the **HugeGraph MCP** shall **识别列名、行数据、数据类型样例和空值情况**。
  - **E26**: WHEN **用户提交 SQL 查询结果**, the **HugeGraph MCP** shall **将其视为结构化表格数据处理，而不要求初始版本直接连接外部数据库**。
  - **E27**: WHEN **用户提供字段映射规则**, the **HugeGraph MCP** shall **根据映射规则生成候选顶点、候选边、属性、主键和边端点**。
  - **O2**: WHERE **用户未提供完整映射规则**, the **HugeGraph MCP** shall **根据表名、列名、主键列、外键列或用户提示生成可编辑的映射建议**。
  - **E28**: WHEN **表格映射生成图数据 payload**, the **HugeGraph MCP** shall **复用统一图数据校验、dry-run、确认和写入流程**。
  - **X10**: IF **表格数据存在主键缺失、重复主键、边端点缺失、边端点无法解析或类型不匹配**, THEN the **HugeGraph MCP** shall **在 dry-run 阶段拒绝或标记风险，不得直接写入**。
  - **X11**: IF **用户请求 MCP 直接连接外部数据库但连接器未启用**, THEN the **HugeGraph MCP** shall **说明当前版本仅支持传入 SQL 结果或表格数据，并给出可接受的数据格式**。
  - **U6**: The **HugeGraph MCP** shall **把自然语言抽图和结构化表格导入统一到同一套图数据 payload、校验和写入机制中**。

### 2.7 安全、权限和确认机制

- **用户故事**: 作为一名 **系统管理员或测试者**, 我希望 **所有危险操作都有一致的安全保护和可验证确认**, 以便 **避免 agent 误写、误改或误删图数据**。
- **验收标准 (EARS 格式)**:
  - **U7**: The **HugeGraph MCP** shall **对所有写入、schema 修改、索引刷新和调试写操作应用统一权限检查**。
  - **S3**: WHILE **readonly 模式开启**, the **HugeGraph MCP** shall **拒绝所有会修改 HugeGraph 或 HugeGraph-AI 索引状态的操作**。
  - **E29**: WHEN **用户请求执行实际写入或 schema apply**, the **HugeGraph MCP** shall **要求 confirm 标记和与 dry-run 绑定的计划校验码**。
  - **X12**: IF **confirm 缺失**, THEN the **HugeGraph MCP** shall **拒绝执行并返回需要确认的下一步动作**。
  - **X13**: IF **计划校验码过期、缺失或不匹配**, THEN the **HugeGraph MCP** shall **拒绝执行并要求重新生成计划**。
  - **X14**: IF **底层调试入口被调用执行危险操作**, THEN the **HugeGraph MCP** shall **仍然执行运行时 guard，而不是只依赖工具是否对用户可见**。
  - **U8**: The **HugeGraph MCP** shall **默认不提供自动删除 schema、批量删除数据或自动回滚能力**。
  - **U13**: The **HugeGraph MCP** shall **从规范化后的精确操作计划生成计划校验码，计划内容至少绑定 payload、目标 graph、graphspace、写入模式、操作顺序和相关 live schema 快照或版本信息**。
  - **E39**: WHEN **schema 变更或图数据导入 dry-run 成功**, the **HugeGraph MCP** shall **返回与已校验计划绑定的 `plan_hash`，并将其作为后续 confirm 执行的必要输入**。
  - **E40**: WHEN **用户请求 confirm 执行**, the **HugeGraph MCP** shall **基于提交的 payload 和当前目标图上下文重新计算 `plan_hash`，并且只有与 dry-run 返回值完全一致时才执行写入或 schema apply**。
  - **X20**: IF **payload、目标 graph、graphspace、写入模式、相关 schema 上下文或操作顺序与 dry-run 时不一致**, THEN the **HugeGraph MCP** shall **拒绝执行并返回 `PLAN_HASH_MISMATCH`**。
  - **X21**: IF **实现无法基于计划内容重新计算计划校验码，或计划校验码与计划内容无关**, THEN the **HugeGraph MCP** shall **不得将该校验码用于确认执行流程**。
  - **O5**: WHERE **计划校验码有效期机制被启用**, the **HugeGraph MCP** shall **在计划过期后拒绝 confirm 执行，并要求用户重新 dry-run**。

### 2.8 统一输出、错误和可观测性

- **用户故事**: 作为一名 **测试者和 Agent 用户**, 我希望 **所有主功能返回结构一致、错误明确、可追踪**, 以便 **自动化测试和 agent 决策都能稳定依赖返回结果**。
- **验收标准 (EARS 格式)**:
  - **U9**: The **HugeGraph MCP** shall **为四类主功能返回统一结构，包含成功状态、数据、错误、warnings、下一步动作和元信息**。
  - **U10**: The **HugeGraph MCP** shall **在元信息中返回请求标识、graph、graphspace、readonly 状态和耗时信息**。
  - **E30**: WHEN **操作产生可恢复问题**, the **HugeGraph MCP** shall **在 warnings 或 next actions 中给出具体建议**。
  - **X15**: IF **HugeGraph Server 不可用**, THEN the **HugeGraph MCP** shall **返回连接失败错误，并提示检查服务地址、graph、graphspace 和认证配置**。
  - **X16**: IF **HugeGraph-AI 不可用或返回不可解析响应**, THEN the **HugeGraph MCP** shall **返回 AI 服务不可用错误或降级建议，而不是返回空答案冒充成功**。
  - **X17**: IF **schema 校验失败**, THEN the **HugeGraph MCP** shall **返回 schema mismatch 错误并列出具体失败项**。
  - **E31**: WHEN **写入或导入成功**, the **HugeGraph MCP** shall **返回批次标识、写入摘要和后续刷新索引建议**。

### 2.9 兼容旧能力和高级调试入口

- **用户故事**: 作为一名 **高级调试用户**, 我希望 **必要时仍能使用底层调试能力**, 以便 **定位问题、验证 Gremlin 或处理主流程之外的特殊情况**。
- **验收标准 (EARS 格式)**:
  - **O3**: WHERE **高级调试能力被保留**, the **HugeGraph MCP** shall **在描述中明确标注其为调试入口，并说明普通用户优先使用主功能流程**。
  - **O4**: WHERE **旧能力与新主功能存在重叠**, the **HugeGraph MCP** shall **保持兼容，但不得绕过统一权限 guard 和 readonly 保护**。
  - **X18**: IF **旧能力返回格式与主功能返回格式不一致**, THEN the **HugeGraph MCP** shall **在文档中说明差异，并优先推动主功能输出统一**。
  - **U11**: The **HugeGraph MCP** shall **避免在用户文档中把底层调试能力和主功能并列呈现为同等推荐路径**。

### 2.10 文档、示例和验收

- **用户故事**: 作为一名 **新用户或测试者**, 我希望 **通过文档和示例理解四个主功能的使用方式和边界**, 以便 **能够独立完成配置、调用和验收**。
- **验收标准 (EARS 格式)**:
  - **E32**: WHEN **用户阅读 README 或集成文档**, the **HugeGraph MCP** shall **以四个主功能为中心组织说明和示例**。
  - **E33**: WHEN **用户查看查询图示例**, the **HugeGraph MCP** shall **包含自然语言查询、证据返回、只读查询语句和危险查询拒绝示例**。
  - **E34**: WHEN **用户查看 schema 管理示例**, the **HugeGraph MCP** shall **包含设计、校验、dry-run、确认执行和 readonly 拒绝示例**。
  - **E35**: WHEN **用户查看导入图数据示例**, the **HugeGraph MCP** shall **包含自然语言文本导入、结构化表格导入、dry-run、确认写入和失败校验示例**。
  - **E36**: WHEN **运行自动化测试**, the **HugeGraph MCP** shall **覆盖四个主功能的成功路径、失败路径、readonly 保护和返回结构稳定性**。
  - **E37**: WHEN **运行端到端验收**, the **HugeGraph MCP** shall **在不破坏用户现有图数据的前提下验证查询、schema dry-run、导入 dry-run 和受控写入流程**。
