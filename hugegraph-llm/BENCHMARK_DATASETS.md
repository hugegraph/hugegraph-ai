# GraphRAG Benchmark Public Dataset Guide

> 本文档说明 HugeGraph-LLM benchmark 当前支持的公开数据集格式、字段转换规则，以及本地已收集数据集的统计信息。目标是帮助后续决定真实跑测评时优先选择哪些数据集、跑多大规模、用哪些指标。

## 1. 数据来源与当前支持范围

公开数据集原始文件默认放在项目内缓存目录：

```text
hugegraph-llm/benchmark_data/raw/
```

该目录已被 `.gitignore` 忽略，不会进入 PR、源码包或 wheel。已有本地数据也可以通过 `--data-root`
指向任意外部目录，例如当前调研工作区里的 `graphrag-benchmark-research/datasets_collected/`。

转换器位于：

```text
hugegraph-llm/src/hugegraph_llm/benchmark/datasets/prepare_external_datasets.py
```

当前 CLI 直接支持以下数据集名。对已登记下载源的数据集，首次使用可加 `--download` 自动拉取到 raw cache：

```bash
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset graphrag-bench-medical --download
```

| `--dataset` | 原始数据集 | benchmark mode | 语言 | 自动下载 | 当前状态 |
|-------------|------------|----------------|------|----------|----------|
| `hotpotqa` | HotpotQA | retrieval | en | 是 | 已支持；下载 dev-distractor split，并从 context 派生 corpus |
| `2wikimultihopqa` | 2WikiMultiHopQA | retrieval | en | 否 | 已支持转换；需手动放置标准化 JSON |
| `musique` | MuSiQue | retrieval | en | 否 | 已支持转换；需手动放置标准化 JSON |
| `anonyrag-chs` | AnonyRAG Chinese | retrieval shell | zh | 是 | 已支持格式转换，但无 gold/retrieved docs |
| `anonyrag-eng` | AnonyRAG English | retrieval shell | en | 是 | 已支持格式转换，但无 gold/retrieved docs |
| `graphrag-bench-medical` | GraphRAG-Bench Medical | retrieval | en | 是 | 已支持，带 `question_type` |
| `graphrag-bench-novel` | GraphRAG-Bench Novel | retrieval | en | 是 | 已支持，带 `question_type` |
| `text2kgbench` | Text2KGBench Wikidata-TekGen | extraction | en | 是 | 已支持 10 个 Wikidata 领域 |
| `anonyrag` | AnonyRAG Chinese + English | retrieval shell | zh/en | 是 | 批量转换 AnonyRAG 两个语言版本 |
| `graphrag-bench` | GraphRAG-Bench Medical + Novel | retrieval | en | 是 | 批量转换 GraphRAG-Bench 两个已接入领域 |
| `all` | 上述全部 | mixed | mixed | 部分 | 批量转换；2Wiki/MuSiQue 仍需手动数据 |

### 1.1 数据下载与缓存

推荐普通用户从项目缓存开始：

```bash
cd hugegraph-llm
uv run python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset graphrag-bench \
  --download \
  --subset-size 20
```

如需把原始数据放到自定义位置：

```bash
uv run python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset text2kgbench \
  --download \
  --cache-dir /path/to/raw-public-datasets
```

如果不加 `--download` 且 raw 文件缺失，CLI 会列出缺少的文件、默认缓存目录、官方来源和可直接执行的下载命令。对于
2WikiMultiHopQA、MuSiQue 这类当前未启用自动下载的数据集，CLI 会明确提示需要放置的标准化 JSON 路径。

> [!IMPORTANT]
> 转换器的原则是 **不发明候选结果**。Retrieval 的 `gold_docs` 来自原数据的 supporting facts / evidence，`retrieved_docs` 来自原数据自带 context / corpus；Text2KGBench 的 `candidate_vertices` / `candidate_edges` 为空，需要接入真实图抽取 pipeline 后再填充。

## 2. 统一 Benchmark 输入格式

### 2.1 Retrieval 格式

适用于 HotpotQA、2WikiMultiHopQA、MuSiQue、AnonyRAG、GraphRAG-Bench。

```json
{
  "samples": [
    {
      "sample_id": "ret_001",
      "question": "question text",
      "gold_docs": ["gold evidence text"],
      "retrieved_docs": ["candidate context text"],
      "gold_answer": "answer text",
      "question_type": "Fact Retrieval"
    }
  ]
}
```

字段含义：

| 字段 | 必填 | 说明 |
|------|------|------|
| `sample_id` | 是 | 样本唯一 ID |
| `question` | 是 | 问题文本 |
| `gold_docs` | 否 | 标准证据，用于 Recall@K / Hit@K / MRR 等离线 retrieval 指标 |
| `retrieved_docs` | 否 | 候选召回上下文；公开数据转换时来自原始 context/corpus，真实跑测时应替换为 HugeGraph-AI pipeline 输出 |
| `gold_answer` | 否 | 标准答案，LLM-Judge retrieval 指标和 answer 指标可使用 |
| `question_type` | 否 | GraphRAG-Bench 的任务难度标签，存在时会触发分层报告 |

### 2.2 Extraction 格式

适用于 Text2KGBench。

```json
{
  "schema": {
    "vertexlabels": [{"name": "film", "primary_keys": ["name"]}],
    "edgelabels": [{"name": "director", "source_label": "film", "target_label": "human"}]
  },
  "samples": [
    {
      "sample_id": "ext_001",
      "input_text": "source sentence",
      "gold_vertices": [{"label": "film", "name": "Inception", "properties": {"name": "Inception"}}],
      "gold_edges": [{"label": "director", "outV": "Inception", "inV": "Nolan", "properties": {}}],
      "candidate_vertices": [],
      "candidate_edges": []
    }
  ]
}
```

字段含义：

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema.vertexlabels` | 是 | 由 Text2KGBench ontology concepts 转换得到 |
| `schema.edgelabels` | 是 | 由 ontology relations 转换得到 |
| `input_text` | 是 | 待抽取文本 |
| `gold_vertices` / `gold_edges` | 是 | 标准图标注 |
| `candidate_vertices` / `candidate_edges` | 否 | 模型或 pipeline 输出；公开数据转换时为空 |

### 2.3 Ablation 格式

公开数据集转换器当前不自动生成 ablation 输入，因为这些数据集不自带四种答案变体。真实跑 HugeGraph-AI pipeline 后，可以把不同策略的答案写成：

```json
{
  "samples": [
    {
      "sample_id": "abl_001",
      "question": "question text",
      "gold_answer": "reference answer",
      "raw_answer": "answer without RAG",
      "vector_only_answer": "answer with vector retrieval only",
      "graph_only_answer": "answer with graph retrieval only",
      "graph_vector_answer": "answer with graph + vector retrieval",
      "raw_context": [],
      "vector_only_context": [],
      "graph_only_context": [],
      "graph_vector_context": [],
      "question_type": "Fact Retrieval"
    }
  ]
}
```

## 3. 各公开数据集转换规则

### 3.1 HotpotQA / 2WikiMultiHopQA

原始字段形态：

- QA 文件：`_id` / `id`, `question`, `answer`, `supporting_facts`, `context`
- corpus 文件：`title`, `text`

转换规则：

| benchmark 字段 | 来源 |
|----------------|------|
| `sample_id` | `_id` 或 `id` |
| `question` | `question` |
| `gold_answer` | `answer` |
| `retrieved_docs` | `context` 中的每个 `(title, sentences)` 拼成 `"title\nsentence..."` |
| `gold_docs` | `supporting_facts` 的 title 优先映射到当前 `context`，找不到时回退到 corpus |

适合用途：

- 多跳 retrieval 离线指标
- 向量召回 / 图召回 pipeline 的候选上下文替换实验
- 低成本 sanity 和 baseline regression

### 3.2 MuSiQue

原始字段形态：

- `id`, `question`, `answer`, `paragraphs`
- `paragraphs[*]` 含 `title`, `paragraph_text`, `is_supporting`

转换规则：

| benchmark 字段 | 来源 |
|----------------|------|
| `sample_id` | `id` |
| `question` | `question` |
| `gold_answer` | `answer` |
| `retrieved_docs` | 全部 `paragraphs` |
| `gold_docs` | `is_supporting=true` 的 paragraphs |

适合用途：

- 更难的多跳 retrieval benchmark
- 检查长候选列表下 Recall@K / MRR 的稳定性
- 比 HotpotQA 更适合作为第二阶段压力测试

### 3.3 AnonyRAG Chinese / English

原始字段形态：

- QA parquet：`question`, `answer`, `query_type`, `relations`, `entities`
- chunks parquet：`idx`, `title`, `chunk`

当前转换规则：

| benchmark 字段 | 来源 |
|----------------|------|
| `sample_id` | `anonyrag_{language}_{row_index}` |
| `question` | QA parquet 的 `question` |
| `gold_answer` | QA parquet 的 `answer` |
| `gold_docs` | 空列表 |
| `retrieved_docs` | 空列表 |

> [!WARNING]
> AnonyRAG 原始 QA 没有 per-question gold chunk，也没有检索器输出。因此当前转换结果只能作为格式 shell，直接跑离线 Recall@K/MRR 没有意义。它更适合在接入真实 retriever 后，用原始 chunks 构建语料，再评 answer correctness / faithfulness / coverage 或人工抽样验证。

适合用途：

- 中文 GraphRAG 端到端验证
- 匿名实体还原、实体关系推理场景
- 中文 prompt / normalization / LLM-Judge 稳定性测试

### 3.4 GraphRAG-Bench Medical / Novel

原始字段形态：

- Questions：`id`, `source`, `question`, `answer`, `question_type`, `evidence`
- Corpus：`corpus_name`, `context`

转换规则：

| benchmark 字段 | 来源 |
|----------------|------|
| `sample_id` | `id` |
| `question` | `question` |
| `gold_answer` | `answer` |
| `question_type` | 原样保留，触发分层报告 |
| `gold_docs` | `[evidence]` |
| `retrieved_docs` | 按 `source` 找到 corpus context 后按换行切段 |

> [!NOTE]
> GraphRAG-Bench 的 `gold_docs` 是 evidence 字符串，而 `retrieved_docs` 是 corpus paragraph。离线 exact/string matching 指标可能偏低甚至为 0；真实评估建议同时看 LLM-Judge 的 `evidence_recall_llm` 或把 pipeline 输出规范成可匹配的 evidence/document ID。

适合用途：

- GraphRAG 专项评测
- 按 `question_type` 看 Fact Retrieval / Complex Reasoning / Contextual Summarize / Creative Generation 分层表现
- 与 GraphRAG-Bench 论文任务设置对齐

### 3.5 Text2KGBench Wikidata-TekGen

原始字段形态：

- ontology JSON：`concepts`, `relations`
- test JSONL：`id`, `sent`
- ground truth JSONL：`id`, `triples`

转换规则：

| benchmark 字段 | 来源 |
|----------------|------|
| `schema.vertexlabels` | ontology `concepts` |
| `schema.edgelabels` | ontology `relations` 的 domain/range |
| `sample_id` | test item `id` |
| `input_text` | test item `sent` |
| `gold_vertices` / `gold_edges` | ground truth triples + ontology |
| `candidate_vertices` / `candidate_edges` | 空列表，等待真实抽取结果填充 |

特殊处理：

- triple 的 `rel` 若在 ontology 中有 range，则转换为 edge。
- relation range 为空时，视为 literal/date 属性，挂到 subject vertex 的 `properties`。
- ontology 未知 relation 会跳过并记录 warning。

> [!IMPORTANT]
> 当前转换器只覆盖 Text2KGBench 的 `wikidata_tekgen` 10 个领域。研究目录统计中 Text2KGBench 总计 6076 句，其中还包括 `dbpedia_webnlg` 2014 句；后者尚未接入当前转换器。

## 4. 数据集统计

统计时间：2026-07-02。统计来源包括本地原始数据目录和 `benchmark_data/external/` 中已转换 JSON。若本地 converted 文件是 smoke 子集，应以原始数据规模为真实跑测容量上限。

### 4.1 Retrieval 数据集总览

| 数据集 | 原始问题数 | 语料规模 | 语言 | gold docs | 当前转换 retrieved docs | 平均候选上下文 | 适合直接离线跑 |
|--------|------------|----------|------|-----------|--------------------------|----------------|----------------|
| HotpotQA | 1000 | 9811 corpus docs | en | 100% 有 | 100% 有 | 9.94 docs/q | 是 |
| 2WikiMultiHopQA | 1000 | 6119 corpus docs | en | 100% 有 | 100% 有 | 10.00 docs/q | 是 |
| MuSiQue | 1000 | 11656 corpus docs | en | 100% 有 | 100% 有 | 19.99 docs/q | 是 |
| AnonyRAG zh | 688 | 2763 chunks | zh | 当前无 | 当前无 | 0 | 否，需先接真实 retriever |
| AnonyRAG en | 709 | 3447 chunks | en | 当前无 | 当前无 | 0 | 否，需先接真实 retriever |
| GraphRAG-Bench Medical | 2062 | 1 corpus record，按转换逻辑约 44 paragraphs/q | en | 100% 有 evidence | 100% 有 | 44.00 paragraphs/q | 可跑，但离线 exact match 解释需谨慎 |
| GraphRAG-Bench Novel | 2010 | 20 corpus records，按转换逻辑约 1 paragraph/q | en | 100% 有 evidence | 100% 有 | 1.00 paragraph/q | 是，适合先跑全量 |

补充统计：

| 数据集 | 平均问题长度 | 平均答案长度 | 备注 |
|--------|--------------|--------------|------|
| HotpotQA | 93.88 chars | 15.05 chars | 多跳 QA，候选上下文固定约 10 篇 |
| 2WikiMultiHopQA | 68.20 chars | 14.06 chars | 问题更短，supporting docs 平均 2.47 |
| MuSiQue | 101.06 chars | 16.97 chars | 候选上下文最多，平均约 20 篇 |
| AnonyRAG zh | 218.65 chars | 63.72 chars | 中文匿名还原，answer 常含实体映射 |
| AnonyRAG en | 481.15 chars | 70.46 chars | 英文问题较长 |
| GraphRAG-Bench Medical | 51.25 chars | 64.25 chars | 原始全量有 4 类 question_type |
| GraphRAG-Bench Novel | 117.30 chars | 30.75 chars | 小说语料，source 分散在 20 本书 |

### 4.2 GraphRAG-Bench 难度分布

| Domain | 总问题数 | Fact Retrieval | Complex Reasoning | Contextual Summarize | Creative Generation | 推荐用途 |
|--------|----------|----------------|-------------------|----------------------|---------------------|----------|
| Medical | 2062 | 1098 | 509 | 289 | 166 | 医学专业语料，适合看复杂问答与总结；每题 44 段上下文，成本较高 |
| Novel | 2010 | 971 | 610 | 362 | 67 | GraphRAG-Bench 全量 smoke 首选；每题上下文更轻 |

决策含义：

- 如果目标是 **快速跑通完整 GraphRAG-Bench 分层报告**，先跑 Novel 全量。
- 如果目标是 **检验长上下文 evidence 覆盖与 LLM-Judge 鲁棒性**，再跑 Medical 子集 200/500，稳定后跑全量。
- Medical 的 corpus 只有一个 source，但转换后每题会带 44 段候选上下文，真实 LLM-Judge 成本明显高于 Novel。

### 4.3 Text2KGBench Wikidata-TekGen 领域统计

| Domain | 样本数 | Concepts | Relations | 平均 gold vertices | 平均 gold edges | 平均原文长度 | 推荐用途 |
|--------|--------|----------|-----------|--------------------|-----------------|--------------|----------|
| movie | 840 | 12 | 15 | 2.86 | 2.17 | 156.05 | 图抽取主力集，样本最多、关系密度最高 |
| music | 675 | 13 | 13 | 2.13 | 1.02 | 139.96 | 第二主力集，规模大且 schema 中等 |
| book | 550 | 20 | 12 | 2.23 | 1.26 | 145.39 | schema 较丰富，适合测类型约束 |
| sport | 487 | 20 | 11 | 2.11 | 0.98 | 147.03 | schema 丰富，关系密度中等 |
| nature | 474 | 14 | 13 | 2.04 | 1.12 | 136.90 | 领域多样，适合扩展覆盖 |
| military | 230 | 13 | 9 | 1.75 | 0.97 | 156.88 | 中小规模 smoke |
| computer | 230 | 15 | 4 | 2.09 | 1.22 | 146.95 | relation 少，适合调试 |
| politics | 214 | 13 | 9 | 1.64 | 0.94 | 156.28 | 中小规模 smoke |
| space | 203 | 15 | 7 | 2.35 | 1.35 | 131.49 | 中小规模 smoke |
| culture | 159 | 15 | 8 | 1.67 | 0.59 | 147.48 | 最小领域，适合快速 CI/smoke |

> [!NOTE]
> 当前转换后的 Text2KGBench 文件 `candidate_*` 均为空，因此直接跑 extraction 指标会反映“空候选”的下限。真实评测需要先用 HugeGraph-AI 抽取 pipeline 填充 candidate graph，再与 gold graph 对比。

### 4.4 AnonyRAG 原始 chunks 统计

| Split | QA 数 | chunks 数 | 平均 chunk 长度 | Query type 分布 | 当前建议 |
|-------|-------|-----------|-----------------|-----------------|----------|
| zh | 688 | 2763 | 962.60 chars | Anonymity Reversion 575；Multiple Choice 113 | 中文端到端优先集，但需要先补检索候选 |
| en | 709 | 3447 | 970.53 chars | Anonymity Reversion 528；Multiple Choice 181 | 英文匿名还原对照集 |

决策含义：

- AnonyRAG 不适合先做离线 retrieval baseline，因为没有 per-question gold chunk。
- 它很适合做 HugeGraph-AI 的中文 GraphRAG demo/真实链路评估：先用 chunks 建索引或构图，再记录 retrieval/answer 输出。
- 如果要量化 retrieval，后续需要补充 gold chunk 标注、或用 LLM-Judge 判断 context relevancy/evidence coverage。

### 4.5 本地已有但当前转换器未接入的数据集

| 数据集 | 本地规模 | 当前状态 | 建议 |
|--------|----------|----------|------|
| WildGraphBench | 1197 QA，12 个 domain | 已下载，未接入转换器 | 作为下一阶段 GraphRAG 真实 Wikipedia 语料扩展，价值高 |
| DocRED / Re-DocRED | train/dev/test 文档级关系抽取 | 已下载，未接入转换器 | 可作为 Text2KGBench 之后的关系抽取扩展 |
| Microsoft GraphRAG Benchmark | HotPotQA filtered 5491；Kevin Scott 125；MSFT transcript 20 | 已下载，未接入转换器 | 可作为 Microsoft GraphRAG 对齐实验 |
| ARES | 大量合成查询 zip，约 1.75 GB | 已下载，未接入转换器 | 体量大，不建议当前 PR 阶段优先 |
| benchmark-qed | AP news + Podcast | 已下载，未接入转换器 | 偏断言式 RAG，可后置 |

WildGraphBench domain 分布：

| Domain | QA 数 |
|--------|-------|
| culture | 155 |
| geography | 98 |
| health | 150 |
| history | 36 |
| human_activities | 140 |
| mathematics | 33 |
| nature | 28 |
| people | 154 |
| philosophy | 70 |
| religion | 106 |
| society | 114 |
| technology | 113 |

## 5. 真实跑测评的推荐路线

### 5.1 第一阶段：低成本离线 baseline

目标：证明 CLI、baseline、report、回归比较链路稳定。

推荐：

1. HotpotQA 100/1000：多跳 QA 标准入门集，gold/retrieved 都完整。
2. 2WikiMultiHopQA 100/1000：补充 compositional 多跳问题。
3. Text2KGBench culture/computer/space：小领域 extraction smoke，用真实抽取结果填 candidate 后跑。

不建议第一阶段使用：

- AnonyRAG：缺 gold docs，直接离线 retrieval 指标不可解释。
- GraphRAG-Bench Medical 全量：每题上下文 44 段，LLM-Judge 成本偏高。

### 5.2 第二阶段：GraphRAG 专项分层评估

目标：对齐 Issue #75 和 GraphRAG-Bench 的难度分层。

推荐：

1. GraphRAG-Bench Novel 全量：2010 题，4 类 question_type，候选上下文轻。
2. GraphRAG-Bench Medical 200/500 子集：先看长上下文 evidence recall 和 LLM-Judge 稳定性。
3. GraphRAG-Bench Medical 全量：在成本可控后再跑。

建议指标：

- Retrieval offline：`recall_at_k,hit_at_k,mrr`
- Retrieval LLM-Judge：`context_precision,context_relevancy,evidence_recall_llm`
- Answer LLM-Judge：`answer_correctness,faithfulness,coverage`

### 5.3 第三阶段：图抽取质量评估

目标：验证 HugeGraph-AI 图抽取输出与 gold graph 的实体、关系、属性、schema 一致性。

推荐 Text2KGBench 顺序：

1. `culture`：159 条，最小，适合快速调试。
2. `movie`：840 条，关系密度最高，适合作为主力图抽取评测。
3. `book` / `sport`：schema concepts 多，适合测类型约束和 schema_validity。
4. `music` / `nature`：补充领域覆盖。

建议指标：

```text
entity_f1,triple_f1,property_f1,schema_validity,structural_integrity,syntax_validity,graph_structure,conflict_detection,temporal_validity
```

### 5.4 第四阶段：中文与端到端真实链路

目标：证明中文场景和真实 GraphRAG pipeline 有效。

推荐：

1. AnonyRAG zh 50/100：先用 chunks 建索引或构图，保存真实 `retrieved_docs` 和 answer variants。
2. AnonyRAG zh 全量 688：稳定后跑 answer LLM-Judge。
3. 中文汽车手册自有数据：作为更贴近 HugeGraph-AI 业务场景的补充集。

建议输出：

- retrieval JSON：记录每题真实 retrieved contexts。
- ablation JSON：记录 raw/vector_only/graph_only/graph_vector 四类答案。
- Markdown report：贴 PR/issue 时优先展示按样本的失败案例。

## 6. 生成与运行命令

生成公开数据集转换文件：

```bash
cd hugegraph-ai

python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset graphrag-bench \
  --download \
  --output-dir hugegraph-llm/benchmark_data/external
```

如果已经在外部目录准备好了原始数据，可用 `--data-root /path/to/raw-public-datasets` 覆盖默认缓存。

生成小样本：

```bash
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset graphrag-bench-novel \
  --download \
  --subset-size 200
```

运行 retrieval：

```bash
cd hugegraph-llm

uv run python -m hugegraph_llm.benchmark run \
  --mode retrieval \
  --data benchmark_data/external/hotpotqa_retrieval.json \
  --metrics recall_at_k,hit_at_k,mrr \
  --offline \
  --format markdown
```

运行 extraction：

```bash
uv run python -m hugegraph_llm.benchmark run \
  --mode extraction \
  --data benchmark_data/external/text2kgbench_movie_extraction.json \
  --metrics entity_f1,triple_f1,property_f1,schema_validity,structural_integrity \
  --offline \
  --format markdown
```

> [!WARNING]
> Text2KGBench 的公开转换文件默认 candidate 为空。上面的 extraction 命令适合验证格式和 runner，不代表模型效果；真实评测前必须先填入 pipeline 输出。

## 7. 当前决策建议

| 决策问题 | 建议 |
|----------|------|
| 先跑哪个公开 retrieval 数据集？ | HotpotQA 100/1000，随后 2WikiMultiHopQA，再 MuSiQue |
| 先跑哪个 GraphRAG-Bench？ | Novel 全量优先，Medical 先子集再全量 |
| 先跑哪个图抽取数据集？ | Text2KGBench culture 调试，movie 主力，book/sport 测 schema |
| 中文评测怎么做？ | AnonyRAG zh 不直接跑离线 retrieval；先接真实 retriever，再跑 answer/LLM-Judge |
| 哪些数据集暂缓？ | ARES、benchmark-qed、DocRED、Microsoft GraphRAG Benchmark，等当前转换器稳定后再接 |

最推荐的近期真实跑测组合：

1. `hotpotqa` 全量 retrieval offline，建立基础 baseline。
2. `graphrag-bench-novel` 全量 retrieval + question_type 分层报告。
3. `text2kgbench_movie` 用真实抽取 candidate 跑 extraction 全指标。
4. `anonyrag-chs` 100 条端到端中文 GraphRAG，重点看 answer correctness / faithfulness。
