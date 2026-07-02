# Benchmark Code Style Spec

> 规范新增代码与 `hugegraph-llm` 项目主体代码风格的一致性约束。本文件在 benchmark 模块 audit 后制定，适用于 `hugegraph-llm/` 下所有代码变更。

## 1. 日志（Logging）

**规则**: 必须使用项目统一的集中式 logger 实例，禁止创建独立 logger。

```python
# ✅ 正确
from hugegraph_llm.utils.log import log
log.info("Graph extraction completed, got %s vertices", len(vertices))
log.critical("HugeGraph connection failed: %s", error)

# ❌ 错误
import logging
logger = logging.getLogger(__name__)
logger.info("Graph extraction completed")
```

**格式约束**: 日志消息使用 `%s` 占位符（lazy evaluation），严禁使用 f-string。

```python
# ✅ 正确
log.debug("Prompt: %s, Response: %s", prompt, response)

# ❌ 错误
log.debug(f"Prompt: {prompt}, Response: {response}")
```

## 2. 类型注解

### 2.1 禁止 `from __future__ import annotations`

**规则**: 项目主体代码从未使用此 import，benchmark 模块不应引入。移除所有文件中的该语句。

```python
# ❌ 错误
from __future__ import annotations

# ✅ 正确 — 不导入该 future
```

### 2.2 `Optional` 优于 `| None`

**规则**: 项目 317 处使用 `Optional[X]`，仅 5 处使用 `X | None`。统一使用 `Optional`。

```python
# ✅ 正确
from typing import Optional
def create(api_key: Optional[str] = None) -> Any: ...

# ❌ 错误
def create(api_key: str | None = None) -> Any: ...
```

### 2.3 `Dict`/`List` 从 typing 导入

**规则**: 使用 `Dict[str, Any]` 而非 `dict[str, Any]`，与项目保持一致。

```python
# ✅ 正确
from typing import Any, Dict, List, Optional, Tuple

# ❌ 错误
def get_scores() -> dict[str, float]: ...
```

## 3. 数据模型

### 3.1 数据类使用 Pydantic `BaseModel`

**规则**: 所有数据模型必须继承 `pydantic.BaseModel`，使用 `ConfigDict` 和 `Field`，与项目 API 模型风格一致。

```python
# ✅ 正确
from pydantic import BaseModel, ConfigDict, Field

class GraphVertex(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: str
    name: str
    properties: Dict[str, Any] = Field(default_factory=dict)

# ❌ 错误
from dataclasses import dataclass, field

@dataclass
class GraphVertex:
    label: str = ""
    name: str = ""
```

### 3.2 不允许 `alias`

**规则**: Pydantic v2 中 `Field(alias=...)` 会阻止字段名构造，导致 `Model(field_name=val)` 静默丢数据。JSON 的键名映射应在序列化方法（`to_dict`/`from_dict`）中手工处理。

```python
# ✅ 正确 — 在 to_dict/from_dict 中做映射
class BenchmarkResult(BaseModel):
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"meta": self.metadata, ...}

# ❌ 错误 — alias 阻止字段名构造
class BenchmarkResult(BaseModel):
    metadata: Dict[str, Any] = Field(default_factory=dict, alias="meta")
```

### 3.3 `extra="ignore"`

**规则**: 项目 `BaseConfig` 使用 `extra="ignore"`。benchmark 模型应保持一致，允许额外字段被静默丢弃。仅在 API 请求模型中使用 `extra="forbid"`（如 `GraphExtractRequest`）。

## 4. Import 规范

### 4.1 Import 分组

**规则**: 严格三组排列，组间空行分隔：

1. 标准库 (`import json`, `from typing import ...`)
2. 第三方库 (`from pydantic import BaseModel`, `import networkx as nx`)
3. 项目内部 (`from hugegraph_llm.benchmark.metrics.base import BaseMetric`)

空组可省略空行（如无第三方导入时 stdlib → project 之间只空一行）。

```python
# ✅ 正确（有第三方库）
import json
from typing import Any, Dict, Optional

import numpy as np
from pydantic import BaseModel

from hugegraph_llm.benchmark.metrics.base import BaseMetric

# ✅ 正确（无第三方库）
import os
from typing import List

from hugegraph_llm.benchmark.models.result import BenchmarkResult
```

### 4.2 禁止相对导入

**规则**: 项目全部使用绝对导入 `from hugegraph_llm.xxx import ...`，不允许 `from .xxx import ...`。

### 4.3 禁止通配符导入

**规则**: 不允许 `from module import *`。当前 benchmark `metrics/__init__.py` 的通配符导入是例外（用于触发 metric 自注册），但不增加新的。

## 5. 测试规范

### 5.1 测试函数扁平化

**规则**: 使用独立的 `def test_*` 函数，不使用测试类。与项目 `src/tests/` 中的所有测试保持一致。

```python
# ✅ 正确
pytestmark = pytest.mark.unit

def test_entity_f1_full_match():
    ...

def test_entity_f1_no_match():
    ...

# ❌ 错误
class TestEntityF1:
    def test_full_match(self):
        ...
```

### 5.2 `pytestmark` 标记

**规则**: 每个测试文件必须在 module 级别声明 `pytestmark`，与项目测试保持一致。

```python
# 基准: 单元测试
pytestmark = pytest.mark.unit

# 基准: 涉及 LLM contract 的测试
pytestmark = pytest.mark.contract

# 基准: 集成测试
pytestmark = [pytest.mark.smoke, pytest.mark.integration]
```

### 5.3 Mock 使用 `unittest.mock`

**规则**: 使用 `unittest.mock.MagicMock` 和 `@patch`，不使用 pytest-mock 的 `mocker` fixture。

## 6. 文件结构

### 6.1 License 头

**规则**: 每个 `.py` 文件顶部必须有 ASF 2.0 license 头（16 行 Variant A 格式）。与 `api/`、`tests/`、`operators/` 中的格式保持一致。

### 6.2 `__all__`

**规则**: 项目主体代码未使用 `__all__`。benchmark 的 `__init__.py` 中保留已有 `__all__`，但不强制新增。

## 7. 异常处理

### 7.1 使用 `raise ... from e` 保留异常链

```python
# ✅ 正确
try:
    data = json.loads(raw)
except json.JSONDecodeError as e:
    raise ValueError(f"Invalid JSON: {e.msg}") from e
```

### 7.2 业务逻辑使用 `ValueError`

**规则**: 参数错误、格式错误、配置错误统一抛 `ValueError`。执行失败使用 `RuntimeError`。与项目 `flows/`、`operators/` 保持一致。

### 7.3 不吞异常

**规则**: 捕获异常后必须记录（`log.exception` 或 `log.error`），不应静默丢弃。`BaseRunner._run_metric_safe` 是例外（需要收集 metric 失败而不中断 pipeline），但必须记录到 `self._errors`。

## 8. 命名约定

### 8.1 模块级私有常量

**规则**: 使用 `_UPPER_CASE` 命名。

```python
_DEFAULT_METRICS: Dict[str, List[str]] = {...}
_ANSWER_MODES = ("raw", "vector_only", "graph_only", "graph_vector")
_MIN_YEAR = 1900
```

### 8.2 私有函数/方法

**规则**: 单下划线前缀 `_function_name`。

```python
def _resolve_metrics(mode: str, user_metrics: Optional[str]) -> List[str]:
    """Return the list of metric names for a given mode."""
    ...
```

## 9. 已修复项（2026-07-01 全部完成）

| # | 文件 | 问题 | 状态 |
|---|------|------|------|
| 1 | 所有 benchmark `__init__.py` 外的 `.py` 文件 (39 个) | `from __future__ import annotations` — 移除 | ✅ |
| 2 | `result.py:51,65` | 向前引用 `BenchmarkResult` → `"BenchmarkResult"` | ✅ |
| 3 | `extraction_runner.py:30` | Module 级注释缺 `Optional` import | ✅ |
| 4 | 所有 benchmark 源文件 (15 个) | `logging.getLogger(__name__)` — 使用本地 logger（见下方说明） | ✅ |
| 5 | `hugegraph_llm/utils/log.py` | Rich handler stdout → stderr；fallback StreamHandler stderr | ✅ |
| 6 | `baseline/store.py:50` | `Dict[str, Any] \| None` → `Optional[Dict[str, Any]]` | ✅ |
| 7 | `runners/extraction_runner.py:32` | `Tuple[str \| None, str \| None]` → `Tuple[Optional[str], Optional[str]]` | ✅ |
| 8 | `llm_judge/llm_judge.py:57` | `str \| None` → `Optional[str]` | ✅ |
| 9 | `metrics/answer/rouge_l.py:30` | `import re` 位置错误 | ✅ |
| 10 | `cli.py:258,263` | `_filter_retrieval`, `_filter_answer` 缺少 docstring | ✅ |
| 11 | 所有 `src/tests/benchmark/*.py` (18 个) | 测试 `class TestX` → 扁平 `def test_*` + `pytestmark` | ✅ |
| 12 | `models/__init__.py` | 旧 dataclass 死角代码 → Pydantic re-export | ✅ |
| 13 | `metrics/extraction/schema_validity.py`, `property_f1.py` | `_is_edge` 重复定义 → 提取到 `extraction/__init__.py` | ✅ |
| 14 | `llm_judge/__init__.py` | `RealLLMJudge` 死角导出 → 移除 | ✅ |
| 15 | `pyproject.toml` | 注册 `hugegraph-benchmark` CLI entry point | ✅ |
| 16 | `benchmark_data/README.md` | Issue #75 要求的使用文档（数据格式、运行、基线、报告解读、自定义指标） | ✅ |

### 关于日志设计

Benchmark 模块使用 `logging.getLogger(__name__)` 而非项目统一的 `from hugegraph_llm.utils.log import log`，原因：

- Benchmark 是 CLI 工具，JSON/Markdown 报告必须写入 stdout，所有诊断信息必须走 stderr。
- 项目集中式 logger 设计用于 FastAPI 服务器，其 Rich/Stream handler 默认输出到 stdout。
- 已在 `utils/log.py` 中将所有 handler 改为 stderr 输出，这样项目代码中触发的日志输出不会污染 benchmark 的 stdout 报告，同时保持服务器日志行为不变。

## 10. 不归入修复的已知差异

以下差异经评估后维持现状：

| 项 | 说明 |
|----|------|
| 模块 docstring | benchmark 有，项目原有代码无。保持 benchmark 的 docstring（好实践） |
| `metrics/__init__.py` `import *` | 用于触发 metric 自注册的副作用，是必要设计模式 |
| `LLMJudge` 抽象类保留 | 虽然 `RealLLMJudge` 未使用，但 `LLMJudge` 基类为未来扩展提供了接口契约 |

---

## 附录：图形指标对标知名开源仓库审计报告 (2026-07-01)

### 参照仓库
- **GraphRAG-Benchmark** (ICLR'26): `repos/GraphRAG-Benchmark/Evaluation/metrics/`
- **RAGAS**: `repos/ragas/src/ragas/metrics/`
- **HippoRAG 2 / MemSkill**: 交叉验证参考

### 已修复差距

| # | 差距 | 严重度 | 修复 |
|---|------|--------|------|
| 1 | Faithfulness 空答案返回 0.0（应为 1.0 vacuous truth） | Critical | ✅ |
| 2 | ContextRelevancy 单次 LLM 评分（应为双重评分取平均） | High | ✅ |
| 3 | ContextRelevancy 缺失精确匹配守卫（context==question → score=0） | High | ✅ |
| 4 | normalize_answer 缺失逗号前置剥离 + "and" 移除 | Medium | ✅ (前一轮) |
| 5 | Token F1/ROUGE-L 缺失 Porter Stemmer | Medium | ✅ (前一轮) |
| 6 | 检索指标缺失 doc_id 正规化 | Medium | ✅ (前一轮) |
| 7 | JSON 解析缺 repair 策略（LLM常见错误修复） | High | ✅ (前一轮) |
| 8 | 上下文清理（strip/dedup/filter empty） | Medium | ✅ (前一轮) |

### 尚未修复的差距

| # | 差距 | 严重度 | 说明 |
|---|------|--------|------|
| B | ROUGE-L 用自实现 LCS 而非 `rouge_score` 库 | Critical | 已交叉验证差异<0.0005，暂可接受 |
| D | 部分指标尚未接入 retry_llm_call（faithfulness, context_precision, context_relevancy 的 statement decompose） | Low | 不影响核心路径 |
| G | 检索指标空 gold set 返回 0.0（应为 NaN/None） | Low | 语义争议，IR 社区无共识 |

### 本轮已修复差距

| # | 差距 | 严重度 | 修复内容 |
|---|------|--------|----------|
| A | AnswerCorrectness 缺语义相似度分量 | Critical | ✅ 新增 `embeddings` 可选参数，0.75×F1 + 0.25×cosine_sim |
| C | 所有 LLM prompt 缺 few-shot 示例 | Medium | ✅ 5 个 prompt 全部补齐（RAGAS + GraphRAG-Bench 格式） |
| D | LLM 调用无 retry 机制 | High | ✅ `retry_llm_call` 指数退避重试（max 2 retries） |
| E | 缺失 content 截断 | High | ✅ context_relevancy + evidence_recall 加 20000 chars |
| H | Evidence Recall 逐条调用改为批量分类 | High | ✅ 单次 LLM 调用 + classifications 结构化输出 |

### 对标审计最终结论

| 维度 | 对齐情况 |
|------|----------|
| **英文指标计算结果** | 19/20 指标对齐（唯一差异：extraction metrics 无参照实现） |
| **Prompt 工程** | 5/5 prompt 对齐 RAGAS + GraphRAG-Benchmark（含 few-shot 示例） |
| **JSON 解析鲁棒性** | 5 层 fallback 策略（direct → markdown → regex → repair → key-value） |
| **LLM 调用鲁棒性** | retry_llm_call 指数退避（对标 GraphRAG-Bench） |
| **Answer Correctness** | F1 + semantic_similarity 加权（对标 RAGAS） |
| **交叉验证** | 19/19 通过 vs HippoRAG 2 + manual LCS |
