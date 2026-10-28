# 实施记录

## 已确认的决策

- 用户明确批准完整首期计划，并要求最大化并行开发、调研、测试和 review。
- 新增 `hugegraph-llm-core`，基础依赖只含 Pydantic，现有应用依赖同一核心。
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

以下结果由主代理完成并汇总；各测试集合可能重叠，不能把数量相加作为独立测试总数。

### 构建与安装

- 将核心源码复制到根工作区之外，使用 `--no-sources` 构建 sdist，并由 sdist 构建 wheel，避免根工作区与旧应用版本约束影响验收。
- 交付 wheel：`hugegraph-llm-core/dist/hugegraph_llm_core-1.8.0-py3-none-any.whl`，49,607 bytes。
- wheel SHA-256：`73e176003ca8d79026201ee61387adca1b10a2af7e1668f247a66b192cf2ef73`。
- 交付 sdist：`hugegraph-llm-core/dist/hugegraph_llm_core-1.8.0.tar.gz`，36,032 bytes。
- sdist SHA-256：`c880200108cae306055ec55b1d8b4d01afc53ac314908f40e12258b922033909`。
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
- 根级 Ruff lint 和 format 检查通过，检查范围共 **558 个文件**；`git diff --check` 通过。

旧模块 unit 集合的首次运行是 **597 passed、3 skipped、2 deselected、3 failed、24 errors**。其中 3 项失败来自测试临时环境路径覆盖与默认路径断言冲突；撤去该覆盖后，`test_config.py` 的 **11 项通过**，其中 8 项与首次结果重叠。24 项错误来自缺失 `litellm.log` 的兼容问题；修复后 `test_litellm_probe_logging.py` 的 **24 项通过**。按这些集合去重后的通过数为 **624**，这是定向修复与重跑的汇总，不是单次完整命令输出；上述 335 项接口集成和 77 项最终关键兼容则各自为单次全通过。

### Review 修复与验证边界

代码 review 已处理 schema 的完整 JSON 合法性、OBJECT 类型、异步 callable 包装识别、串行调用线程亲和、工厂模型资源所有权以及清理过程中的取消传播。

随后补充 provider 错误与 token usage 日志脱敏：错误日志只包含异常类型，usage 只保留合法数字，不记录响应正文；新增 28 项回归。上表是此修复之后重建产物的最终四版本结果，工作区完整核心测试更新为 611 项，独立 provider 合同更新为 54 项。旧 models、config 与日志集合仍为 **222 passed、2 skipped**。

截至本记录，未调用真实 LLM 或图数据库服务，未对外发布包或进行生产部署。这些回归验证 SDK、安装隔离与兼容合同，不构成真实模型抽取准确率评测。

## 后续授权：PR 与 Docker 实测

用户追加授权提交 PR 并执行 Docker 实测。应用 Docker 镜像已经完成构建；容器启动和 HTTP 实测正在进行，当前不记录为通过。PR 尚未创建，链接与最终容器验证结果待主代理确认后补充。
