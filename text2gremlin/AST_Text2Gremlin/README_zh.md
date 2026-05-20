# Text2Gremlin 语料泛化

[English](./README.md) | [中文](README_zh.md)

基于AST和模版生成大量多样化的 Gremlin 查询及其自然语言描述，并通过 LLM 进行多阶段数据增强与偏好数据合成，用于训练和评估 text2gremlin 模型。

## 快速开始

### 1. 环境配置
Python 版本：3.12.10
```bash
pip install -r requirements.txt
```

### 2. 配置文件
复制示例配置文件并填入你的配置：
```bash
cp config_example.json config.json
```

编辑 `config.json`，填入 LLM API 配置：
```json
"llm": {
    "base_url": "http://your-llm-server:port/v1",
    "api_key": "your-api-key",
    "model": "your-model-name",
    "temperature": 1.0,
    "max_retries": 3,
    "max_concurrency": 5,
    "save_interval": 50,
    "timeout": 40
}
```

> ⚠️ `config.json` 包含敏感信息，已被 `.gitignore` 忽略，请勿提交到版本控制。

### 3. 运行

#### 阶段一：AST 泛化生成语料库
```bash
python generate_corpus.py
```

#### 阶段二～五：LLM 增强流水线
```bash
# 执行全部 LLM 增强阶段（翻译 → 迁移 → 合并 → DPO）
python run_llm_pipeline.py

# 从指定阶段开始
python run_llm_pipeline.py --stage migrate

# 只执行某个阶段
python run_llm_pipeline.py --stage merge --stop merge
```

各阶段也可独立运行：
```bash
# 多风格翻译
python -m llm_augment.generalize_llm

# 场景迁移
python -m llm_augment.migrate_scenario

# 数据集合并
python -m llm_augment.merge_dataset

# DPO 偏好数据生成
python -m llm_augment.generate_dpo_data
```

#### 语法分析
```bash
python analyze_syntax.py
```

---

## 数据生成流水线

```text
阶段 1: AST 泛化          generate_corpus.py
         251 模板 → ~1500 条 (query + 简单描述)
              ↓
阶段 2: LLM 多风格翻译    llm_augment/generalize_llm.py
         ×6 风格 → ~9000 条 (4固定 + 2随机语气)
              ↓
阶段 3: 场景迁移           llm_augment/migrate_scenario.py
         ×20 场景 → ~30000 条 (CRUD 均衡, 语法检查)
              ↓
阶段 4: 数据集合并         llm_augment/merge_dataset.py
         合并翻译+迁移 → 统一 text2gremlin 数据集
              ↓
阶段 5: DPO 偏好数据       llm_augment/generate_dpo_data.py
         A类(多任务组合) + B类(单任务) + C类(长链拆解)
         → ~8900 条偏好数据 (21 个领域)
```

---

## 项目结构

```text
├── generate_corpus.py          # AST 泛化主程序
├── run_llm_pipeline.py         # LLM 增强流水线统一入口
├── analyze_syntax.py           # Gremlin 语法分布分析
├── gremlin_templates.csv       # 查询模板 (251条)
├── config.json                 # 配置文件 (gitignored)
├── config_example.json         # 配置示例
├── requirements.txt            # Python 依赖
│
├── llm_augment/                # LLM 增强数据生成包
│   ├── __init__.py
│   ├── generalize_llm.py       # 阶段2: 多风格翻译
│   ├── migrate_scenario.py     # 阶段3: 场景迁移
│   ├── merge_dataset.py        # 阶段4: 数据集合并
│   └── generate_dpo_data.py    # 阶段5: DPO 偏好数据
│
├── base/                       # AST 泛化核心引擎
│   ├── generator.py            # 解析泛化控制器 + 语法检查
│   ├── Config.py               # 配置管理
│   ├── Schema.py               # Schema 和数据管理
│   ├── GremlinParse.py         # 数据结构定义
│   ├── GremlinExpr.py          # 复杂表达式 (谓词、匿名遍历等)
│   ├── GremlinTransVisitor.py  # AST 解析
│   ├── TraversalGenerator.py   # 遍历生成器
│   ├── GremlinBase.py          # 翻译引擎
│   ├── gremlin/                # ANTLR 生成的 Gremlin 解析器
│   └── template/               # 翻译字典
│
├── db_data/                    # 数据和 Schema
│   ├── schema/                 # 图数据库 schema
│   └── reference/              # 场景迁移用的多领域 schema
│
└── output/                     # 输出目录
    └── preference_data/        # DPO 偏好数据
```

---

## 配置说明

### LLM 配置 (`config.json` → `llm`)

| 字段 | 说明 | 默认值 |
|------|------|--------|
| base_url | LLM API 地址 | 必填 |
| api_key | API 密钥 | 必填 |
| model | 模型名称 | 必填 |
| temperature | 采样温度 | 1.0 |
| max_retries | 单条最大重试次数 | 3 |
| max_concurrency | 并发请求数 | 5 |
| save_interval | 增量保存间隔 | 50 |
| timeout | 单次请求超时 (秒) | 40 |

### 模板文件 (`gremlin_templates.csv`)

| 列名 | 说明 | 示例 |
|------|------|------|
| template | Gremlin 查询模板 | `g.V().hasLabel('person')` |
| description | 模板描述（可选） | 查询所有人 |

### 组合控制 (`base/combination_control_config.json`)

控制 AST 泛化阶段的查询生成数量：
- 链长度分类: 短链(≤4步)、中链(5-6步)、长链(7-8步)、超长链(≥9步)
- 数据值填充: 中间步骤填1个值，终端步骤填2-3个值
- 属性泛化: 根据链长度动态调整泛化程度

---

## 输出格式

### AST 泛化结果 (`generated_corpus_*.json`)
```json
{
  "metadata": { "total_unique_queries": 1564, "..." : "..." },
  "corpus": [
    { "query": "g.V().hasLabel('person')", "description": "..." }
  ]
}
```

### LLM 翻译结果 (`llm_translated_*.json`)
```json
{
  "corpus": [
    {
      "query": "g.V().hasLabel('person')",
      "translations": [
        { "style": "zh_formal", "text": "查询所有人类型的顶点" },
        { "style": "en_casual", "text": "Find all person nodes" }
      ]
    }
  ]
}
```

### 场景迁移结果 (`migrated_*.json`)
```json
{
  "migrations": [
    {
      "target_domain": "ecommerce",
      "generated_samples": [
        { "operation": "read", "query": "g.V()...", "natural_language": "..." }
      ]
    }
  ]
}
```

### DPO 偏好数据 (`preference_data/dpo_data_merged.json`)
```json
{
  "metadata": {
    "total_samples": 8920,
    "rejected_count": 3032,
    "type_distribution": { "A": 4380, "B": 2318, "C": 2222 },
    "domain_distribution": { "movie": 401, "ecommerce": 399, "..." : "..." },

  },
  "samples": [
    {
      "task_id": "pref_MOVI_A_0001",
      "task_type": "A",
      "domain": "movie",
      "source_queries": [
        { "text": "查询所有演员", "gremlin": "g.V().hasLabel('person')" }
      ],
      "input": { "instruction": "请帮我查询所有演员并更新..." },
      "chosen": { "style": "groovy", "code": "def actors = g.V()..." },
      "rejected": { "style": "gremlin", "code": "g.V().hasLabel..." },
      "preference_reason": ["Groovy 写法更清晰...", "..."]
    }
  ]
}
```

---

## 核心特性

### AST 泛化
从一个模板生成多个变体，智能控制组合爆炸，自动去重：
```text
模板: g.V().hasLabel('person').out('acted_in')
  → g.V().hasLabel('movie').out('acted_in')
  → g.V().hasLabel('person').out('directed')
  → ...
```

### LLM 多风格翻译
每条查询翻译为 6 种风格（4 固定 + 2 随机）：
- 中文正式 / 中文口语 / 英文正式 / 英文口语
- 中英混合 / 省略表达 / 问答式 / 错别字

### 场景迁移
将电影领域数据迁移到 20 个业务场景，生成 CRUD 均衡的数据，每条 Gremlin 经过 ANTLR 语法检查。

### DPO 偏好数据
三类任务生成 Groovy vs Gremlin 偏好对，覆盖 21 个领域（movie + 20 个迁移领域），合计 8920 条：

- **A 类（多任务组合，4380 条）**：选 2~5 条简单查询组合为复合任务
  - chosen: Groovy 命令式写法（def 变量、.next()、返回 map）
  - rejected: 纯 Gremlin 函数式写法（as/select/project 强行单链）
  - 自动分析命令冲突（如删除后更新），调整执行顺序或拒绝合成
- **B 类（单任务，2318 条）**：简单查询不需要 Groovy 包装
  - chosen: 原始纯 Gremlin
  - rejected: 过度工程化的 Groovy 包装
- **C 类（长链拆解，2222 条）**：复杂长链查询拆解为多步
  - chosen: Groovy 分步写法
  - rejected: 原始长链 Gremlin

### 流水线特性
- 并发控制：`asyncio.wait(FIRST_COMPLETED)` + Semaphore + 批量任务创建
- 增量保存：每 50 条自动保存，断点可恢复
- Pydantic 验证：所有 LLM 输出严格校验格式
- ANTLR 语法检查：纯 Gremlin 代码经过语法验证（Groovy 代码跳过，因变量引用不兼容 ANTLR）
- 单条重试：失败自动重试（指数退避），不影响其他任务
- 代码无注释：所有生成的 Groovy/Gremlin 代码禁止包含注释
