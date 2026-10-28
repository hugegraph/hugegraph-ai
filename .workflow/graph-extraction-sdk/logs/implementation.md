# 实施记录

## 已确认的决策

- 用户明确批准完整首期计划，并要求最大化并行开发、调研、测试和 review。
- 最终发行名为 `hugegraph-llm-sdk`，导入名为 `hugegraph_llm_sdk`，对外称 HugeGraph-LLM SDK；基础依赖只含 Pydantic，现有应用依赖同一 SDK。
- SDK 与 `hugegraph-llm/` 应用保持根目录平级，表达应用调用 SDK 的依赖方向，不提供旧名兼容 shim。
- 名称为后续更多灵活调用的 LLM 能力保留空间；当前只交付图设计、校验、抽取、审阅和有限修复。
- 新 SDK 默认审阅修复、并发 1；旧 UI 和 HTTP 保留原默认和响应合同。
- 核心沿用 HugeGraph schema 语义，首期不连接数据库、不扩展到召回或写库。
- 独立 wheel 的 Python 3.10–3.13 验证必须在根工作区之外运行。

## 并行工作划分

运行时与属性图、schema 与 prompt、厂商适配、旧入口兼容、SDK 隔离测试、文档与 CI 分别由不同代理负责；主代理装配公共 API、依赖与包，并进行交叉 review 和最终验证。

## 文档与 CI

- 新 README 描述源码路径／wheel 安装、最小接入、结果状态、扩展协议、异步、并发和旧应用边界。
- 三个离线示例覆盖设计后修改 schema、校验触发修复、原生异步调用；固定响应只验证集成合同，不代表模型质量。
- 新 CI 在临时目录构建并安装 wheel，基础矩阵运行独立隔离 smoke、示例和核心测试；Python 3.11 单独验证可选厂商适配器。
- 此处不记录尚未执行的测试为成功；最终验证结果由主代理追加。

## 文档与示例局部验证

本节记录重命名前的局部验证。重命名后的发行验收另见最终验收，不以旧结果代替新包验证。

- 使用现有 Python 3.11 环境及核心源码路径分别执行 basic.py、customization.py、async_example.py，全部通过。
- 自定义校验示例确认 1 次修复、3 次模型调用，并返回审阅通过的图。
- 四个示例文件通过 Ruff lint 和 format check；新增 CI YAML 可解析，包含四版本基础矩阵及独立 provider 契约任务。
- 上述是局部验证，不代替工作区外的 wheel 安装验证，也不代表真实 LLM 质量。

## 模型资源所有权

SDK 仅清理 `model_factory` 创建且提供关闭方法的模型；调用方直接传入的模型仍由调用方管理。同步批次调用 close，异步批次优先等待 aclose，只有同步关闭方法时使用线程适配。完成、异常和取消均覆盖清理路径；模型自身的共享全局连接池不由 SDK 接管。

同步批次在调用线程完成清理，不承诺模型创建与关闭的线程相同。取消线程适配后的等待不保证停止已经发出的同步请求；关闭可能与请求收尾重叠，文档明确保留此边界。

## Schema 可选声明边界

schema 校验按实际声明信息执行。省略 propertykeys 时不检查全局属性声明引用；省略标签 properties 时属性名不受该列表限制，显式空列表则禁止属性。需要严格白名单与类型验证的调用方必须显式提供完整声明，SDK 不补默认值。

## 最终验收

用户在已有实现和 Docker 验证完成后确认使用 `hugegraph-llm-sdk` / `hugegraph_llm_sdk`。README 已统一命名、安装方式与根级平行目录说明；代码、依赖、CI 和旧应用引用由主代理完成更名。

### 新发行名产物与安装

冻结 README 与源码后，在仓库工作区之外构建 sdist，再由 sdist 构建 wheel；随后使用全新虚拟环境独立安装验收。

- wheel：`hugegraph-llm-sdk/dist/hugegraph_llm_sdk-1.8.0-py3-none-any.whl`，**49,742 bytes**。
- wheel SHA-256：`2564d747dc38c72c5236e3e7b2c34055d079b2b1cf0bd27e83d0fbd2cc2c77e5`。
- sdist：`hugegraph-llm-sdk/dist/hugegraph_llm_sdk-1.8.0.tar.gz`，**36,353 bytes**。
- sdist SHA-256：`4fc1043b6417c53ece155179a3f2640ae6c871ff5d8b0a142ce34b9febf57b5a`。

安装后确认发行元数据 `Name=hugegraph-llm-sdk`，`hugegraph_llm_sdk` 从环境的 `site-packages` 加载；旧发行名和旧导入模块均不可见。

另在外部 Python 3.12 项目通过新 SDK 路径执行 `uv add --editable`，依赖仅为 SDK、Pydantic 及其传递依赖；关闭审阅的抽取返回 `validated`。

### 新发行名独立环境验证

| Python | 基础环境测试 | 隔离 smoke | sdist 中的三个离线示例 |
| --- | --- | --- | --- |
| 3.10.22 | 556 passed，55 skipped | 通过 | 全部通过 |
| 3.11.14 | 556 passed，55 skipped | 通过 | 全部通过 |
| 3.12.14 | 556 passed，55 skipped | 通过 | 全部通过 |
| 3.13.5 | 556 passed，55 skipped | 通过 | 全部通过 |

基础环境未安装模型厂商 extras，55 项可选依赖测试显式跳过。隔离 smoke 仍禁止文件写入、联网、旧应用和厂商模块导入，并校验新旧发行与导入隔离。另建 Python 3.11 环境安装全部 extras，provider 契约测试为 **54 passed、1 skipped**；唯一跳过项需要未安装的旧应用。

### 更名后的工作区与旧应用回归

- 完整 SDK 测试：**611 passed**。
- 旧入口兼容定向回归：**81 passed**。
- 旧模型与配置相关回归：**258 passed、2 skipped**，跳过项依赖外部服务。
- 根级 Ruff lint 与 format 检查全部通过，检查范围 **561 个文件**。

这些集合可能重叠，不能相加作为独立测试总数。

### 更名后的 Docker 与 PR

重命名前的验证容器已清理。更名后的完整镜像构建与应用实测通过，使用正常启动流程，以非 root 用户运行。

- 镜像：`hugegraph-llm:sdk-decoupling`，ID 为 `sha256:aa88d3c7c3d2812d32f10a95d068466b05b625818574cebaa875d4293459f113`。
- 容器：`hugegraph-llm-sdk-check`；HTTP 已通，记录时 Docker 健康检查仍为 `starting`，不将其记为 `healthy`。
- 容器元数据确认安装 `hugegraph-llm-sdk` **1.8.0**，模块路径为 `/home/work/hugegraph-llm-sdk/src/hugegraph_llm_sdk/__init__.py`；旧发行名和旧导入模块均不可见。
- 首页 HTTP 返回 **200**；本地 OpenAI 协议 fixture 实测全部通过，最终图为 **2 个顶点、1 条边**。
- fixture 共 **7 次调用**：probe 1 次、schema 1 次、legacy 1 次、extract 1 次、review 2 次、repair 1 次；结果保存在 `/tmp/hugegraph-llm-sdk-renamed-smoke.json`。

本次使用真实 HTTP 传输与固定模型响应验证完整流程，没有调用真实模型服务或图数据库，也没有对外发布包、镜像或部署生产服务。

[PR #84](https://github.com/hugegraph/hugegraph-ai/pull/84) 保持 ready，主代理正在按新 SDK 名称更新标题与说明，随后推送更名提交。新提交的远端 CI 状态以 PR 为准，不沿用此前 head 的成功结果。

## 重命名前验收（历史记录）

以下结果由主代理在更名前完成并汇总，仅用于追踪首期实现的验证过程；不能作为新发行名的安装与产物验收。各测试集合可能重叠，不能把数量相加作为独立测试总数。

### 构建与安装

- 将核心源码复制到根工作区之外，使用 `--no-sources` 构建 sdist，并由 sdist 构建 wheel，避免根工作区与旧应用版本约束影响验收。
- 重命名前 wheel：49,607 bytes。
- wheel SHA-256：`73e176003ca8d79026201ee61387adca1b10a2af7e1668f247a66b192cf2ef73`。
- 重命名前 sdist：36,171 bytes；已包含 ASF 表头修复。
- sdist SHA-256：`c93f05995090281ee6cc042944b9eae96361df82d1dfef098c665d38bb5e1230`。
- 外部 Python 3.12 项目通过 `uv add --editable` 安装成功，安装依赖为核心包、Pydantic 及其传递依赖；运行关闭审阅的抽取得到 `validated`。

### 独立 wheel 验证

| Python | 基础环境测试 | 隔离 smoke | 三个离线示例 |
| --- | --- | --- | --- |
| 3.10.22 | 556 passed，55 skipped | 通过 | 全部通过 |
| 3.11.14 | 556 passed，55 skipped | 通过 | 全部通过 |
| 3.12.14 | 556 passed，55 skipped | 通过 | 全部通过 |
| 3.13.5 | 556 passed，55 skipped | 通过 | 全部通过 |

基础环境未安装模型厂商 extras，相应供应商测试显式跳过。隔离 smoke 禁止文件写入、联网、旧应用及厂商模块导入，仍可完成设计、修改 schema、校验和同步／异步抽取。

Python 3.11 的独立 wheel 环境安装全部模型 extras 后，provider 契约测试为 **54 passed、1 skipped**；跳过的是需要旧 `hugegraph_llm` 的兼容测试，该旧应用没有安装进独立环境。

矩阵验证发现的旧 `contract` marker 孤立警告已清理；独立 strict-markers 属性图回归为 **333 passed，无警告**。

### 工作区与旧入口回归

- 完整核心测试：**611 passed**。
- 旧模块关键兼容 review 测试：**77 passed**。
- 此前运行的旧模块 integration 集合：**335 passed**。
- 此前运行的 models、config 与日志相关集合：**222 passed、2 skipped**，跳过项依赖外部服务。
- 后续完整旧 LLM CI unit 集合：**1,334 passed、3 skipped、18 deselected**；覆盖率 **63.58%**，通过 **34%** 门槛。
- 根级 Ruff lint 和 format 检查通过，检查范围共 **561 个文件**；`git diff --check` 通过。

旧模块 unit 集合的首次运行是 **597 passed、3 skipped、2 deselected、3 failed、24 errors**。其中 3 项失败来自测试临时环境路径覆盖与默认路径断言冲突；撤去该覆盖后，`test_config.py` 的 **11 项通过**，其中 8 项与首次结果重叠。24 项错误来自缺失 `litellm.log` 的兼容问题；修复后 `test_litellm_probe_logging.py` 的 **24 项通过**。按这些集合去重后的通过数为 **624**，这是定向修复与重跑的汇总，不是单次完整命令输出；上述 335 项接口集成和 77 项最终关键兼容则各自为单次全通过。

### Review 修复与验证边界

代码 review 已处理 schema 的完整 JSON 合法性、OBJECT 类型、异步 callable 包装识别、串行调用线程亲和、工厂模型资源所有权以及清理过程中的取消传播。

随后补充 provider 错误与 token usage 日志脱敏：错误日志只包含异常类型，usage 只保留合法数字，不记录响应正文；新增 28 项回归。上表是此修复之后、SDK 更名之前重建产物的四版本结果，工作区完整核心测试更新为 611 项，独立 provider 合同更新为 54 项。旧 models、config 与日志集合仍为 **222 passed、2 skipped**。

截至本记录，未调用真实 LLM 或图数据库服务，未对外发布包、镜像或进行生产部署。这些回归验证 SDK、安装隔离与兼容合同，不构成真实模型抽取准确率评测。

## 重命名前的 PR 与 Docker 实测（历史记录）

以下镜像 ID 和运行结果来自 SDK 更名前的应用构建；更名后的镜像重建与运行结果待补充。

用户追加授权提交 PR 并执行 Docker 实测。草稿 [PR #84](https://github.com/hugegraph/hugegraph-ai/pull/84) 已创建。首次提交除许可证检查外的其他 workflow 均成功。许可证 CI 发现核心 pyproject 缺少 ASF 表头，已补齐，并为移动后的根 .dockerignore 添加同一表头；未修改检查规则。重建后的 wheel 哈希不变，sdist 已更新。远端检查和评审状态以 PR 为准。

### 镜像构建与运行

- 镜像：`hugegraph-llm:sdk-decoupling`，ID 为 `sha256:9ec5ef50ea29f075896936600a5b547aa10eb3e55ce455da541070ed28382600`。
- 容器：`hugegraph-llm-sdk-check`，实测时为 `running`、`healthy`；端口映射为 `127.0.0.1:18001 -> 8001`。
- 使用镜像正常 CMD 启动，运行用户为非 root（uid 1000）；运行时版本为 Python **3.10.16**、核心包 **1.8.0**、pycgraph **3.2.2**。
- 首页 HTTP 返回 **200**。
- 镜像没有包含宿主 `.env`、`config_prompt`、`.git` 或构建时使用的 secret CA。

Docker 构建将 `.dockerignore` 移至仓库根以覆盖实际构建上下文。原 pycgraph wheel 需要镜像没有提供的 `GLIBCXX_3.4.32`，因此 `uv sync` 跳过该 wheel，并从同一锁定 commit 源码编译 pycgraph，保留 Bookworm 与 Python 基线。构建过程中仅通过 build secret 为 pip、uv 和 git 临时提供 CA 信任。

### HTTP 与模型协议实测

容器通过真实 HTTP 请求连接本地 OpenAI 协议 fixture，完成模型探测、schema 设计、旧抽取入口以及审阅修复流程。fixture 共收到 **7 次调用**：probe 1 次、schema 1 次、legacy 1 次、extract 1 次、review 2 次、repair 1 次，最终返回 **2 个顶点、1 条边**。结果保存在 `/tmp/hugegraph-llm-sdk-smoke.json`。

此实测覆盖应用启动、HTTP 合同、OpenAI 协议传输与完整修复流程；fixture 使用固定响应，没有连接真实模型服务或图数据库。

## PR #84 独立交叉审计与修复（2026-10-28）

用户要求先发布最终评分和 comments，再修复并尝试推送。三个独立审查代理分别覆盖运行时、schema/图数据对抗输入、旧应用/provider/打包，由主审交叉复现与裁决。

对 `cc3bd4521658a6dd86ce1a129cd6ae03363065ff` 的审计先发布了 [8.4/10 评分](https://github.com/hugegraph/hugegraph-ai/pull/84#issuecomment-6461882699) 和 [4 条行级 comments](https://github.com/hugegraph/hugegraph-ai/pull/84#pullrequestreview-5678428711)，确认发布时工作区无源码改动，之后才实施修复。

### 修复与取舍

- 工厂模型按最多 `max_workers` 块一组执行，组结束后关闭客户端，再启动下一组。保留同步调用线程关闭、异步 worker 停止后清理、直接传入模型由调用方管理的合同。该修复替代前述初次实现的整批末尾关闭策略。
- 保留已关闭模型的身份引用直至批次结束，避免工厂再次返回同一个客户端或对象 ID 复用误判；使用字典代替线性扫描。这里限制打开的资源，不声称批次内存为常数。
- 每组等待最慢块后再启动下一组，以较小实现范围保留清理线程和取消语义；没有修改旧应用使用的底层调度器。
- 客户端自己的 `aclose()` 抛出取消时，仍尝试关闭同组其他客户端，再传播取消，并保留原始异常或调用方取消。
- 类工厂检查元类构造调用，支持实例具有异步 `__call__` 的普通类及其 partial；真正的异步工厂继续被拒绝。
- 校验显式边 frequency 与排序键要求，以及排序键与可空键的冲突。省略 frequency 不补默认值；自定义顶点 ID 策略的旧 primary_keys 元数据保持兼容。

### 本轮最终验证

- 完整核心测试：**646 passed**，比审计基线增加 **35** 个用例。
- 旧 LLM CI unit/contract 集合：**1,334 passed、3 skipped、18 deselected**；覆盖率 **63.62%**，通过原有 **34%** 门槛。
- 另有独立 reviewer 编写的 **5** 项所有权/取消交叉检查全部通过；这些与主测试覆盖重叠，不累加为总数。
- 原始资源复现：进程 fd 上限 64、100 块、并发 1，从 **61 成功 / 39 失败、峰值 61 个客户端**变为 **100 成功、峰值 1 个客户端**。
- 原始类工厂复现中 class/lambda 两种方式均成功；关闭取消复现仍传播 CancelledError，关闭状态从 `[False, True]` 变为 `[True, True]`。
- 根级 Ruff lint/format 通过，检查 **561** 个文件；`git diff --check` 通过。

独立安装从工作区之外的 sdist 构建 wheel；以下基础环境仅安装 wheel、pytest 和基础依赖（Pydantic 2.14.1），未安装 provider extras，因此相应 **55** 项显式跳过：

| Python | 已安装 wheel 测试 | 隔离 smoke | 三个离线示例 |
| --- | --- | --- | --- |
| 3.10.22 | 591 passed、55 skipped | 通过 | 全部通过 |
| 3.11.17 | 591 passed、55 skipped | 通过 | 全部通过 |
| 3.12.14 | 591 passed、55 skipped | 通过 | 全部通过 |
| 3.13.16 | 591 passed、55 skipped | 通过 | 全部通过 |

wheel SHA-256：`bd383c3035bfa9fa6bbbe05281a31508c2e66ff069d85356b87e603b7fa839af`。

sdist SHA-256：`d012a30f6c2330b4f8b59bd6fff2e5a8d65a77e8cd239da9e329c3840d6d3df1`。

验证中修正了 Python 3.10 新增测试对取消消息包装方式的假设，沿异常上下文确认原取消原因，生产取消语义不变。旧应用首次全量运行因缺失 NLTK stopwords 数据出现 1 项失败，补齐官方数据后完整重跑得到上述结果。受限执行环境的标准库 asyncio 线程关闭等待问题通过独立最小复现定位，最终测试在正常线程运行环境完成；隔离 smoke 使用独立空目录，避免共享临时目录的并行写入干扰。

本轮未重建 Docker，也未调用真实模型或图数据库；复审不将既有 Docker 记录冒充为此次执行结果。修复提交与新 CI 结论见 PR。
