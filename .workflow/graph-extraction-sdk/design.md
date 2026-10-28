# 设计：HugeGraph-LLM SDK 与旧应用适配

## 命名与目录

发行包为 `hugegraph-llm-sdk`，Python 导入名为 `hugegraph_llm_sdk`，对外品牌为 HugeGraph-LLM SDK。当前公开能力是图 schema 设计与校验、属性图抽取、审阅和有限修复；未来更多 LLM 调用能力只作为扩展方向，不计入本期实现。

SDK 位于仓库根级 `hugegraph-llm-sdk/`，与 `hugegraph-llm/` 应用平级。这样外部项目可以独立安装、引用和修改 SDK，目录结构也直接反映应用依赖 SDK 的方向。此次更名不提供旧包名兼容 shim。

## 依赖方向

外部 Python 项目直接依赖 `hugegraph-llm-sdk`；现有 `hugegraph-llm` 通过兼容层调用同一 SDK。SDK 只依赖标准库和 Pydantic。厂商适配器通过 `openai`、`ollama`、`litellm` extras 安装，按模块惰性导入。

SDK 不能反向导入旧应用配置、UI、调度器、图客户端、文件上传或日志初始化。旧应用负责配置持久化和模型工厂；UI 负责展示、通知和表单保存。

## 公共接口

- `design_schema` / `adesign_schema` 返回 `SchemaDraft(schema, issues)`。
- `validate_schema` 返回 `list[Issue]`，不修改输入或补默认值。
- `extract_graph` / `aextract_graph` 返回 `ExtractionResult(status, chunks, graph)`。
- 模型提供最小 `generate(prompt=...)` / `agenerate(prompt=...)` 协议；`FunctionModel` 和 `ThreadedModel` 连接调用方现有实现。
- `GraphPrompts` 分别提供抽取、审阅、修复提示词；设计提示词单独传入。
- 自定义 validator 接收 `(graph, schema, text)`，返回结构化问题，参与修复后的重新校验。
- 公共 bundle 与同步／异步单块、批量运行入口支持替换步骤。

## 执行与结果

字符串为一块，字符串列表保留调用方分块。抽取前完成参数和 schema 校验。默认审阅修复使用 2 次审阅、1 次修复预算；SDK 默认并发 1，显式并发须无参 `model_factory` 为每块创建独立模型。旧运行时的并发默认通过兼容层保留。

默认流程只有 `final` 汇总入图；关闭审阅后的 `validated` 也视为完成。块级错误保留状态、问题、失败阶段与调用计数。总体状态为 succeeded / partial / failed，图汇总按输入顺序拼接，不进行跨块语义合并。

异步优先原生模型调用；取消传播并清理 worker。同步模型的线程适配不保证取消已发出的远端请求。

PR 交叉审计后，工厂模型改为每组最多 `max_workers` 块的有界生命周期：一组 worker 全部停止后释放该组客户端，再启动下一组。同步关闭继续在调用线程执行，异步关闭保留取消保护。该方案用组间等待换取较小的修复范围，不改动公共低层运行时或旧应用调度；同一实例跨组重复返回仍被拒绝。客户端自身关闭取消时也必须尝试清理同组其他客户端。

schema 校验增加显式边约束：排序键不能可空，声明的 frequency 与排序键要求必须一致。省略 frequency 时不推断默认值；自定义顶点 ID 策略携带旧应用注入的 primary_keys 继续按既有兼容规则处理。

## 迁移策略

迁移抽取运行时、属性图校验和纯 ID helper；默认 prompt 脱离配置类。共享 schema 设计与输入归一化逻辑下沉，旧 UI 保留错误展示、样例与表单持久化适配。模型传输、重试和截断逻辑共享，旧模型类保留历史默认行为。

不改变旧 HTTP 输出字段和状态，不把新 SDK 的默认审阅策略带入旧入口。

## 验证策略

SDK 行为测试、异步与状态隔离测试、旧入口真实 SDK 契约回归并行进行。独立 wheel CI 复制 SDK 目录到工作区之外构建，验证 Python 3.10–3.13；基础环境只装 wheel 与测试工具，另用 Python 3.11 安装厂商 extras 验证请求边界。

更名后重新构建 sdist 和 wheel，并重复独立安装与应用兼容验证；重命名前的产物摘要与测试数量只作为历史记录，不用于证明新发行名的安装验收。
