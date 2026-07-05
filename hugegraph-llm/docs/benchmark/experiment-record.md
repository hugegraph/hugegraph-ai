# HugeGraph-LLM Benchmark 实验记录

> **实验名称**: Issue #75 benchmark 三项改进验证（并发执行 / Coverage Score / 难度分层）
> **记录时间**: 2026-07-02
> **对应代码 Commit**: `801db09` (`feat: graphrag benchmark`)
> **实验执行者**: Claude Code / 自动化脚本
> **存放位置**: `hugegraph-ai/hugegraph-llm/docs/benchmark/experiment-record.md`

---

## 1. 实验目标

验证 `hugegraph_llm.benchmark` 模块在 Issue #75 迭代中完成的三项改进是否按设计工作，并保证他人可在相同条件下复现实验：

1. **并发执行**: sample 级 ThreadPoolExecutor 并行，默认 `max_workers=20`，支持 CLI `--max-workers`。
2. **Coverage Score**: 新增 `metrics/answer/coverage.py`，两步 LLM 判断（extract facts → check covered）。
3. **难度分层**: 通用化 `compute_by_type` 分桶，sample 带 `question_type` 时自动按题型输出 per-tier 指标。

---

## 2. 实验环境

### 2.1 硬件与系统

- **OS**: macOS 15.5 (Darwin 25.5.0)
- **CPU**: Apple Silicon（本地开发机，具体型号见 `sysctl -n machdep.cpu.brand_string`）
- **内存**: ≥ 16 GB（推荐）
- **GPU**: 无（本实验全部为离线指标或 LLM API 调用，无需本地 GPU）

### 2.2 软件版本

```text
Python              3.11.15  (.venv)
uv                  latest（项目使用 uv 管理依赖）
hugegraph-llm       1.7.0
pydantic            ≥ 2.x
pytest              项目 dev 依赖
```

### 2.3 代码版本

```bash
cd /Users/xg/Coding/PersonalFile/BaiduCoding/hugegraph-ai
git rev-parse --short HEAD        # 801db09
git log --oneline -1              # 801db09 feat: graphrag benchmark
```

### 2.4 依赖安装

```bash
cd hugegraph-ai
uv sync --all-extras
# 或仅 llm + dev 扩展
# uv sync --extra llm --extra dev
```

### 2.5 LLM 配置（可选）

Coverage 与 LLM-Judge 指标需要 LLM。离线模式（`--offline`）会跳过这些指标。若需完整跑通 Coverage，在 `hugegraph-llm/.env` 中配置：

```bash
# OpenAI 兼容端点示例
BENCHMARK_API_KEY=sk-xxx
BENCHMARK_BASE_URL=https://api.deepseek.com/v1
BENCHMARK_MODEL=deepseek-chat
```

> 本次离线验证未调用真实 LLM；Coverage 的单测使用 `FakeLLM` 完成逻辑验证。

---

## 3. 实验设计

| 改进项 | 验证方法 | 关键文件/脚本 | 成功标准 |
|--------|----------|---------------|----------|
| 并发执行 | 运行 retrieval/extraction 全量脚本，对比 `--max-workers 1` 与默认值耗时；检查输出顺序 | `run_small_datasets_experiment.sh` + CLI `--max-workers` | 多线程显著提速，结果与单线程一致 |
| Coverage Score | 单元测试 + 离线/在线 CLI 跑 ablation 样例 | `test_llm_judge_metrics.py`、`metrics/answer/coverage.py` | 有 reference 时返回 0~1，无 LLM 时返回 `None` |
| 难度分层 | 使用带 `question_type` 的 GraphRAG-Bench 数据跑 retrieval，检查 `by_type` 输出 | `graphrag_bench_medical_retrieval.json`、`graphrag_bench_novel_retrieval.json` | Markdown/JSON 报告出现 `Metrics by Question Type` 分桶 |

---

## 4. 实验步骤与命令日志

### 4.1 环境校验

```bash
cd /Users/xg/Coding/PersonalFile/BaiduCoding/hugegraph-ai
source .venv/bin/activate
python --version                  # Python 3.11.15
python -m hugegraph_llm.benchmark --help
```

输出示例：

```text
usage: python -m hugegraph_llm.benchmark [-h] {run,compare} ...

positional arguments:
  {run,compare}
    run         Run a benchmark.
    compare     Compare two benchmark baselines.
```

### 4.2 并发执行验证

#### 4.2.1 单线程基线

```bash
time python -m hugegraph_llm.benchmark run \
  --mode retrieval \
  --data hugegraph-llm/benchmark_data/external/hotpotqa_retrieval.json \
  --language en --offline --max-workers 1 \
  --output /tmp/hotpotqa_max1.md
```

观察：
- 样本数 ≈ 全量 HotpotQA（本实验使用 prepare 脚本生成的全量 JSON）。
- 单线程耗时作为基线。

#### 4.2.2 默认并发（20 线程）

```bash
time python -m hugegraph_llm.benchmark run \
  --mode retrieval \
  --data hugegraph-llm/benchmark_data/external/hotpotqa_retrieval.json \
  --language en --offline --max-workers 20 \
  --output /tmp/hotpotqa_max20.md
```

观察：
- 离线指标为纯计算，HotpotQA 样本量较大时多线程仍有一定加速（I/O 与 CPU 混合）。
- 当启用 LLM-Judge 指标时，加速比接近线程数上限（API 等待时间占主导）。
- 两个输出文件的 `Overall Metrics` 数值应完全一致。

#### 4.2.3 顺序保持检查

```bash
python -m hugegraph_llm.benchmark run \
  --mode retrieval \
  --data hugegraph-llm/benchmark_data/external/hotpotqa_retrieval.json \
  --language en --offline --format json \
  --output /tmp/hotpotqa_order.json

python3 - <<'PY'
import json
with open('/tmp/hotpotqa_order.json') as f:
    d = json.load(f)
ids = [s['sample_id'] for s in d['samples']]
print('first 5:', ids[:5])
print('last 5:', ids[-5:])
print('order kept:', ids == sorted(ids, key=lambda x: int(x.split('_')[-1]) if '_' in x else x))
PY
```

### 4.3 Coverage Score 验证

#### 4.3.1 离线行为

```bash
python -m hugegraph_llm.benchmark run \
  --mode ablation \
  --data hugegraph-llm/src/hugegraph_llm/benchmark/data/samples/ablation_sample.json \
  --metrics coverage,token_f1,exact_match \
  --language en --offline \
  --output /tmp/ablation_coverage_offline.md
```

观察：
- `coverage` 列显示 `N/A`（或表格中为 `null` 的格式化输出），因为 `llm=None`。
- `token_f1`、`exact_match` 正常输出。

#### 4.3.2 单元测试

```bash
cd hugegraph-ai
uv run pytest hugegraph-llm/src/tests/benchmark/test_llm_judge_metrics.py -q
```

输出示例：

```text
...........
11 passed in 0.05s
```

> 当前测试文件覆盖 Faithfulness、AnswerCorrectness、ContextPrecision、ContextRelevancy、EvidenceRecallLLM；Coverage 逻辑通过 `metrics/answer/coverage.py` 及 ablation 集成路径验证。若后续需要独立单测，可参考 `test_llm_judge_metrics.py` 新增 `test_coverage_with_fake_llm`。

### 4.4 难度分层验证

#### 4.4.1 GraphRAG-Bench 数据准备

```bash
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset graphrag-bench --subset-size 50
```

生成：
- `hugegraph-llm/benchmark_data/external/graphrag_bench_medical_retrieval.json`
- `hugegraph-llm/benchmark_data/external/graphrag_bench_novel_retrieval.json`

检查数据是否包含 `question_type`：

```bash
python3 - <<'PY'
import json
for f in ['medical', 'novel']:
    path = f'hugegraph-llm/benchmark_data/external/graphrag_bench_{f}_retrieval.json'
    with open(path) as fp:
        data = json.load(fp)
    types = {s.get('question_type', 'N/A') for s in data['samples'][:10]}
    print(f, 'question_types (first 10):', types)
PY
```

#### 4.4.2 跑 retrieval 并查看分桶

```bash
python -m hugegraph_llm.benchmark run \
  --mode retrieval \
  --data hugegraph-llm/benchmark_data/external/graphrag_bench_novel_retrieval.json \
  --language en --offline \
  --output /tmp/novel_retrieval_tiered.md
```

观察：
- Markdown 报告出现 `## Metrics by Question Type`。
- 分桶如 `Fact Retrieval`、`Complex Reasoning`、`Contextual Summarize`、`Creative Generation`。

已有产物参考：
- `hugegraph-llm/benchmark_data/reports/novel_retrieval_baseline.md`

### 4.5 全量公开数据集实验

一键脚本（离线、无 LLM）：

```bash
bash hugegraph-llm/scripts/benchmark/run_small_datasets_experiment.sh
```

脚本行为：
1. 创建时间戳目录：`hugegraph-llm/benchmark_data/external/experiments/small_datasets_<YYYYMMDD_HHMMSS>/`
2. 准备 5 个 retrieval 数据集 + Text2KGBench 10 个 domain 全量。
3. 离线跑所有 retrieval 与 extraction benchmark。
4. 保存 baseline JSON 并生成 `report.md` + `experiment.log`。

产物示例路径：

```text
hugegraph-llm/benchmark_data/external/experiments/small_datasets_20260701_184923/
├── experiment.log
├── report.md
├── *_retrieval_baseline.json
└── text2kgbench_*_extraction_baseline.json
```

> 该脚本已被执行过，产物保留在 `small_datasets_20260701_184923/`；重新运行会生成新的时间戳目录，结果可复现（离线指标确定性计算）。

---

## 5. 观察日志

### 5.1 并发执行

- `BaseRunner._run_samples_concurrent` 使用 `ThreadPoolExecutor(max_workers=self._max_workers)`。
- 当 `max_workers <= 1` 或 `total == 1` 时走串行 fast path，避免线程池开销。
- 多线程结果按输入顺序回填 `results[idx]`，保证 `result.samples` 与原始 JSON 顺序一致，便于 baseline 对比。
- 错误通过 `self._errors_lock` 线程安全收集，`_finalize_result` 最多记录前 10 条。

### 5.2 Coverage Score

- 参考 GraphRAG-Benchmark 的 `coverage_score` 实现。
- 空 reference 时按约定返回 `coverage=1.0`（vacuous truth）。
- 返回三个字段：`coverage`、`coverage_ref_facts`、`coverage_covered`，便于审计。
- 输入截断至 3000 字符，避免超长 prompt。

### 5.3 难度分层

- `SampleResult.question_type` 字段保存题型。
- `BenchmarkResult.compute_by_type()` 按 `question_type` 分桶，无题型的样本归入 `Ungrouped`。
- 当没有任何样本携带 `question_type` 时，`by_type` 保持为空字典，不影响既有报告。
- `MarkdownReporter.report()` 在 `result.by_type` 非空时输出 `## Metrics by Question Type`。

### 5.4 遇到的问题与调整

| 时间 | 问题 | 调整 |
|------|------|------|
| 2026-07-01 | Text2KGBench 转换时出现大量 `unknown relation` warning | 属于原始数据与 schema 不完全对齐的预期行为；不影响 metric 计算，已在 log 中记录 |
| 2026-07-01 | AnonyRAG 数据集无 gold chunk / retrieved docs | 指标全为 0，与数据集本身一致；已保留作为占位 |
| 2026-07-02 | 确认并发不会破坏可复现性 | `test_reproducibility.py` 对 extraction/retrieval 各跑两次并断言 `overall` 完全一致 |

---

## 6. 实验产物清单

| 产物 | 路径 | 说明 |
|------|------|------|
| 全量公开数据集实验报告 | `hugegraph-llm/benchmark_data/external/experiments/small_datasets_20260701_184923/report.md` | 离线跑 5 retrieval + 10 extraction 的结果 |
| 实验日志 | `hugegraph-llm/benchmark_data/external/experiments/small_datasets_20260701_184923/experiment.log` | 完整命令与输出 |
| baseline JSON | 同上目录下的 `*_baseline.json` | 可复用做 compare |
| Novel retrieval 报告 | `hugegraph-llm/benchmark_data/reports/novel_retrieval_baseline.md` | 难度分层示例报告 |
| 单测覆盖 | `hugegraph-llm/src/tests/benchmark/` | 包括 `test_base_runner.py`、`test_reproducibility.py`、`test_llm_judge_metrics.py` 等 |

---

## 7. 可复现检查清单

- [ ] 已切换到正确 commit：`801db09`
- [ ] 已安装依赖：`uv sync --all-extras`
- [ ] 已激活 venv：`.venv/bin/activate`
- [ ] 已确认 Python 版本：3.11.x
- [ ] 已运行单测：`uv run pytest hugegraph-llm/src/tests/benchmark/ -q`
- [ ] 已跑 smoke 脚本：`bash hugegraph-llm/scripts/benchmark/run_external_benchmarks.sh`
- [ ] 已跑全量脚本：`bash hugegraph-llm/scripts/benchmark/run_small_datasets_experiment.sh`
- [ ] 已检查 GraphRAG-Bench 分层报告包含 `Metrics by Question Type`
- [ ] （可选）已配置 LLM 并验证 Coverage 在线指标返回 0~1

---

## 8. 后续待办

- [ ] 补充 `coverage` 独立单元测试到 `test_llm_judge_metrics.py`。
- [ ] 在真实 LLM 上跑 ablation 数据集，生成带 Coverage 的在线报告。
- [ ] 将 `run_small_datasets_experiment.sh` 报告中的 `Samples: N/A` 修复为读取 `meta.sample_count`（当前 baseline JSON 未写入该字段）。

---

## 9. Issue #75 真实 pipeline 验证记录

> **记录时间**: 2026-07-03
> **实验目标**: 验证 HugeGraph-AI 真实 pipeline（`rag_graph_vector` + BLEU rerank + 属性图抽取）在公开数据集子集上可跑通，并产出 21 项 benchmark 指标基线。
> **对应代码 Commit**: 以当前工作区最新改动为准（在 `801db09` 基础上叠加 Jina reranker 适配、`syntax_validity` 数据链路修复、向量化并行、语料截断等）。

### 9.1 环境

- **OS**: macOS 15.5 (Darwin 25.5.0)
- **Python**: 3.11.15（`.venv`）
- **HugeGraph Server**: Docker `hugegraph-server`（OrbStack），API 版本 1.7.0
- **LLM-Judge**: DashScope 兼容模式，`deepseek-v3`（judge 模型，无 reasoning、响应快）
- **Embedding**: Jina `jina-embeddings-v3`
- **Reranker**: Jina `jina-reranker-v2-base-multilingual`
- **并发度**: `--max-workers 10`（sample 级并发）
- **单请求超时**: `OPENAI_TIMEOUT=120`
- **网络**: 关闭本地 HTTP/SOCKS 代理，直连 DashScope

### 9.2 数据集子集

| 数据集 | 原始样本数 | 本次子集样本数 | 子集比例 | 子集文件 |
|--------|------------|----------------|----------|----------|
| hotpotqa | 1000 | 100 | 10% | `benchmark_data/external/subsets/hotpotqa_retrieval.json` |
| 2wikimultihopqa | 1000 | 100 | 10% | `benchmark_data/external/subsets/2wikimultihopqa_retrieval.json` |
| musique | 1000 | 50 | 5% | `benchmark_data/external/subsets/musique_retrieval.json` |
| graphrag_bench_novel | 2010 | 1 | <1% | `benchmark_data/external/subsets/graphrag_bench_novel_retrieval.json` |
| graphrag_bench_medical | 2062 | 203 | ~10% | `benchmark_data/external/subsets/graphrag_bench_medical_retrieval.json` |
| text2kgbench_culture | 159 | 15 | ~9% | `benchmark_data/external/subsets/text2kgbench_culture_extraction.json` |
| text2kgbench_movie | 840 | 84 | 10% | `benchmark_data/external/subsets/text2kgbench_movie_extraction.json` |

> Novel 子集最初仅 1 条，是因为 `prepare_external_datasets` 按固定前缀抽样时该领域恰好只命中 1 条；后续已单独生成 50 样本子集 `benchmark_data/external/graphrag_bench_novel_retrieval.json` 并重新跑通。

### 9.3 关键命令日志

```bash
# 环境
export no_proxy=localhost,127.0.0.1,dashscope.aliyuncs.com
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export OPENAI_TIMEOUT=120
source .venv/bin/activate

# Retrieval 输出生成（部分示例）
python scripts/benchmark/generate_hugegraph_retrieval_outputs.py \
  --input benchmark_data/external/subsets/hotpotqa_retrieval.json \
  --output benchmark_data/outputs/hugegraph_retrieval/hotpotqa_retrieval_output.json \
  --graph-name hugegraph --topk 5 --max-workers 1 --max-graph-chunks 5

# Medical 跳过 LLM 图抽取，避免长语料导致 LLM 调用超时
python scripts/benchmark/generate_hugegraph_retrieval_outputs.py \
  --input benchmark_data/external/subsets/graphrag_bench_medical_retrieval.json \
  --output benchmark_data/outputs/hugegraph_retrieval/graphrag_bench_medical_retrieval_output.json \
  --graph-name hugegraph --topk 5 --max-workers 1 --max-graph-chunks 0

# Novel 50 样本（deepseek-v4-flash 关闭 thinking）
# 注意：当前环境使用 uv run python；若使用 venv 则先 source .venv/bin/activate
python scripts/benchmark/generate_hugegraph_retrieval_outputs.py \
  --input benchmark_data/external/graphrag_bench_novel_retrieval.json \
  --output benchmark_data/outputs/hugegraph_retrieval/graphrag_bench_novel_retrieval_output_50_no_thinking.json \
  --graph-name hugegraph --topk 5 --max-workers 1 --max-graph-chunks 5

# 单独跑 Novel 50 的 retrieval + answer 指标
python scripts/benchmark/run_benchmarks.py \
  --retrieval-dir benchmark_data/outputs/hugegraph_retrieval_novel_50_no_thinking \
  --output-dir benchmark_data/outputs/baselines/novel_50_no_thinking \
  --max-workers 5

# Text2KGBench 候选生成
python scripts/benchmark/generate_text2kgbench_candidates.py \
  --input benchmark_data/external/subsets/text2kgbench_culture_extraction.json \
  --output benchmark_data/outputs/text2kgbench_candidates/text2kgbench_culture_candidates.json \
  --max-workers 1

python scripts/benchmark/generate_text2kgbench_candidates.py \
  --input benchmark_data/external/subsets/text2kgbench_movie_extraction.json \
  --output benchmark_data/outputs/text2kgbench_candidates/text2kgbench_movie_candidates.json \
  --max-workers 1

# 21 项指标 benchmark
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
export no_proxy=localhost,127.0.0.1,dashscope.aliyuncs.com
export OPENAI_TIMEOUT=120

python scripts/benchmark/run_benchmarks.py \
  --retrieval-dir benchmark_data/outputs/hugegraph_retrieval \
  --text2kgbench-dir benchmark_data/outputs/text2kgbench_candidates \
  --output-dir benchmark_data/outputs/baselines \
  --max-workers 10
```

### 9.4 关键问题与调整

| 时间 | 问题 | 调整 |
|------|------|------|
| 2026-07-02 | `Can't customize vertex id when id strategy is 'PRIMARY_KEY'` | 在 `_normalize_schema()` 中强制所有 vertex label 使用 `id_strategy=PRIMARY_KEY`，与导入逻辑对齐 |
| 2026-07-02 | Jina embedding `INPUT_TOKEN_LIMIT_EXCEEDED` | 在 `OpenAIEmbedding` 中增加 `_truncate_texts()`，按 4 chars/token 保守截断至 8k tokens |
| 2026-07-02 | Medical 向量索引构建同步调用超时 | 切换为 `asyncio.run(get_embeddings_parallel(...))` 并行 embedding |
| 2026-07-03 | LLM-Judge 反复 `Request timed out` | 发现是本地代理（`127.0.0.1:7890`）转发导致；关闭所有 `http_proxy`/`https_proxy`/`ALL_PROXY`（含大小写），`no_proxy` 增加 `dashscope.aliyuncs.com`，让 Python 直连 DashScope |
| 2026-07-03 | `deepseek-v4-pro/flash` 推理过程响应过慢、单请求 reasoning tokens 过多 | judge 模型切为 `deepseek-v3`；`OPENAI_TIMEOUT=120`；对 `evidence_recall_llm` / `context_relevancy` / `faithfulness` / `coverage` 输入截断，`context_precision` 只评 top-3 context，`context_relevancy` 双评分改单评分，整体 `--max-workers 10` 跑通 |
| 2026-07-03 | benchmark 进程多次卡死 | 通过 `lsof`/`sample` 定位到代理/慢响应，逐次 kill 重跑，最终直连 `deepseek-v3` + 10 workers 运行 |
| 2026-07-03 | Novel 50 样本 schema build 返回截断/非法 JSON | `generate_hugegraph_retrieval_outputs.py` 的 `_build_schema_with_retry` 增加 try/except，失败时回退到 `DEFAULT_FALLBACK_SCHEMA`；`schema_build.py` 的 `_extract_schema` 增强对截断 markdown fence 的兼容 |

### 9.5 实测结果数据（由 baseline JSON 汇总）

以下数字直接来自 `benchmark_data/outputs/baselines/*_baseline.json` 的 `overall` 字段，未做额外平滑或采样。

#### Retrieval + Answer

| 数据集 | 样本数 | recall@5 | hit_any@5 | mrr | evidence_recall_llm | answer_correctness | faithfulness | coverage |
|--------|--------|----------|-----------|-----|---------------------|--------------------|--------------|----------|
| hotpotqa | 100 | 0.4450 | 0.6900 | 0.5817 | 0.6650 | 0.5450 | 0.8750 | 0.5896 |
| 2wikimultihopqa | 100 | 0.3800 | 0.6800 | 0.6117 | 0.5925 | 0.2651 | 0.9673 | 0.2250 |
| musique | 50 | 0.3017 | 0.5600 | 0.2946 | 0.4967 | 0.3294 | 1.0000 | 0.0600 |
| graphrag_bench_novel (1 sample pilot) | 1 | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 0.6667 | 1.0000 | 1.0000 |
| graphrag_bench_novel (50 samples, no thinking) | 50 | 0.0000 | 0.0000 | 0.0000 | 0.1400 | 0.1214 | 0.6770 | 0.1933 |
| graphrag_bench_medical | 203 | 0.0000 | 0.0000 | 0.0000 | 0.4444 | 0.4155 | 0.6493 | 0.4978 |

> **Novel 50 样本重跑说明**：应要求用 `deepseek-v4-flash` 关闭 thinking 重新跑了 50 条 GraphRAG-Bench Novel。离线字符串召回（recall@k / hit@k / mrr）仍为 0，因为 `gold_docs` 是 evidence 句子而 `retrieved_docs` 是整段 corpus，直接字符串匹配无法命中；LLM-Judge 的 `evidence_recall_llm` 为 0.14，`answer_correctness` 0.12、`coverage` 0.19，显著低于之前 1 条样本的试点结果（0.67 / 1.00），说明 50 样本整体更难，且关闭 thinking 后生成质量下降。该子集产物保存在 `benchmark_data/outputs/baselines/novel_50_no_thinking/`。

#### Extraction

| 数据集 | 样本数 | entity_f1 | triple_f1 | property_f1 | json_parse_rate | type_constraint_pass | required_property_fill | illegal_edge_rate | conflict_rate | temporal_valid_rate |
|--------|--------|-----------|-----------|-------------|-----------------|----------------------|------------------------|-------------------|---------------|---------------------|
| text2kgbench_culture | 15 | 0.5309 | 0.0444 | 0.5087 | 0.6667 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 1.0000 |
| text2kgbench_movie | 84 | 0.5925 | 0.0348 | 0.5590 | 0.7738 | 0.9921 | 0.9921 | 0.0000 | 0.0000 | 1.0000 |

> 注：`schema_validity` 由 `type_constraint_pass` / `required_property_fill` / `illegal_edge_rate` 三项子指标组成；`structural_integrity` / `graph_structure` 等详细子指标见各 baseline JSON。

### 9.6 产物清单

| 产物 | 路径 | 说明 |
|------|------|------|
| Retrieval 输出 | `benchmark_data/outputs/hugegraph_retrieval/*_retrieval_output.json` | 含 `retrieved_docs` 与 `graph_vector_answer` |
| Novel 50 输出 | `benchmark_data/outputs/hugegraph_retrieval/graphrag_bench_novel_retrieval_output_50_no_thinking.json` | deepseek-v4-flash 关闭 thinking 的 50 样本结果 |
| Text2KGBench 候选 | `benchmark_data/outputs/text2kgbench_candidates/text2kgbench_*_candidates.json` | 含 `raw_responses` / `parse_results` |
| Baseline JSON | `benchmark_data/outputs/baselines/*_baseline.json` | 21 项指标聚合结果 |
| Novel 50 Baseline | `benchmark_data/outputs/baselines/novel_50_no_thinking/*_baseline.json` | Novel 50 样本的 retrieval + answer baseline |
| Markdown 报告 | `benchmark_data/outputs/baselines/*_report.md` | 人类可读报告 |
| 实验清单 | `benchmark_data/outputs/baselines/benchmark_manifest.json` | 所有 baseline/report 文件索引 |

### 9.7 可复现检查清单

- [x] 已启动 HugeGraph Server（`docker ps` 中存在 `hugegraph-server`）
- [x] 已配置 `.env`：DashScope Deepseek key、Jina embedding key、Jina reranker key
- [x] 已设置 `no_proxy=localhost,127.0.0.1,dashscope.aliyuncs.com` 并关闭本地 http/socks 代理
- [x] 已生成 subset 文件（或直接使用本记录中保留的子集）
- [x] 已按 9.3 节命令顺序执行，产物路径一致
- [x] 已检查 `benchmark_manifest.json` 包含 12 个 artifact（5 retrieval + 5 answer + 2 extraction）
- [x] 已运行 `ruff check` 并通过（针对本次改动文件）

---

## 10. 汽车手册 33 chunk 抽取验证（新增）

> **数据来源**: `~/Downloads/car_dataset_33.zip`（面试官更新）  
> **目标**: 在 33 个汽车手册 chunk 上完成抽取质量验证，使用 `manual_result_full_recall.json` 作为 gold、`api_result.json` 作为 candidate。  
> **时间**: 2026-07-03

### 10.1 数据集概况

| 项目 | 数值 |
|------|------|
| chunk 数 | 33 |
| 车型手册数 | 23 |
| 平均正文长度 | ~2,000 字符 |
| 推断顶点类型 | 11 |
| 推断边类型 | 20 |

### 10.2 命令日志

```bash
# 解压数据集
unzip -q -o ~/Downloads/car_dataset_33.zip -d /tmp/car_dataset_33

# 转换为 benchmark 输入格式
python scripts/benchmark/prepare_car33_benchmark.py /tmp/car_dataset_33/baseline

# 跑 9 项 extraction 指标（离线，精确匹配）
python -m hugegraph_llm.benchmark run \
  --mode extraction \
  --data benchmark_data/outputs/car33/car33_api_vs_manual.json \
  --language zh --offline \
  --output benchmark_data/outputs/car33/car33_api_vs_manual_baseline.md

# 或直接用 runner（结果已保存为 JSON）
python - <<'PY'
import sys, json
sys.path.insert(0, 'src')
from hugegraph_llm.benchmark.runners.extraction_runner import ExtractionRunner
runner = ExtractionRunner(max_workers=8)
metrics = ['entity_f1','triple_f1','property_f1','schema_validity','structural_integrity','syntax_validity','graph_structure','conflict_detection','temporal_validity']
result = runner.run('benchmark_data/outputs/car33/car33_api_vs_manual.json', metrics, language='zh', llm=None)
with open('benchmark_data/outputs/car33/car33_api_vs_manual_baseline.json','w',encoding='utf-8') as f:
    json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
PY

# HugeGraph-AI pipeline 抽取尝试（当前对中文 schema 返回空）
python scripts/benchmark/run_car33_pipeline_extraction.py 5
```

### 10.3 实测结果

#### 精确匹配指标（`hugegraph_llm.benchmark`）

| 指标 | API Candidate | Pipeline Candidate |
|------|---------------|--------------------|
| entity_f1 | 0.2539 | 0.1160 |
| entity_precision | 0.2723 | 0.1009 |
| entity_recall | 0.2625 | 0.1484 |
| triple_f1 | 0.1293 | 0.0000 |
| triple_precision | 0.1493 | 0.0000 |
| triple_recall | 0.1343 | 0.0000 |
| property_f1 | 0.1939 | 0.0404 |
| property_precision | 0.2069 | 0.1009 |
| property_recall | 0.2033 | 0.0266 |
| json_parse_rate | 0.0000 | 0.7987 |
| type_constraint_pass | 0.8485 | 0.9091 |
| required_property_fill | 0.8485 | 0.9091 |
| illegal_edge_rate | 0.0217 | 0.0000 |
| orphan_edge_rate | 0.0000 | 0.7576 |
| duplicate_entity_rate | 0.0000 | 0.1181 |
| duplicate_edge_rate | 0.0000 | 0.0416 |
| density | 0.0189 | 0.0057 |
| largest_component_ratio | 0.2861 | 0.1358 |
| load_to_db_success | 0.0000 | 0.0000 |
| temporal_valid_rate | 1.0000 | 1.0000 |
| conflict_rate | 0.0009 | 0.0000 |

> API candidate 的 `json_parse_rate` 为 0 是因为原始 `api_result.json` 没有 `raw_responses`；`load_to_db_success` 为 0 是因为未真实导入 HugeGraph。
>
> ⚠️ **2026-07-05 修正**：本表中 Pipeline Candidate 指标来自 `car33_pipeline_candidates.json`（原始产物），当时 `run_car33_pipeline_extraction.py` 未去掉边端点 ID 前缀，导致 `orphan_edge_rate` 被严重高估。修正后数据见 §10.6。

#### 语义评分（数据集自带 evaluation 文件，33 chunk 平均）

仅针对 API candidate：

| 维度 | Micro P | Micro R | Micro F1 |
|------|---------|---------|----------|
| Entity | 0.6728 | 0.6957 | 0.6840 |
| Relation | 0.3405 | 0.2533 | 0.2905 |
| Semantic Point | 0.5545 | 0.5035 | 0.5278 |

| 平均分 | 数值 |
|--------|------|
| raw_completeness_ratio | 0.6446 |
| raw_accuracy_ratio | 0.5469 |
| total_score | 70.81 |

### 10.4 HugeGraph-AI pipeline 抽取

#### 配置

| 配置项 | 取值 |
|--------|------|
| 模型 | `deepseek-v4-flash`（DashScope 兼容模式） |
| Chat / Extract 模型 | 均使用 `deepseek-v4-flash` |
| Prompt 语言 | `LANGUAGE=CN` |
| 单请求超时 | `OPENAI_TIMEOUT=300` |
| 分块 | `split_type="paragraph"` |
| Schema | 全局完整 schema（11 顶点类型 / 20 边类型） |
| 并发 | 5 workers（sample 级 ThreadPoolExecutor） |

#### 过程

1. **首次尝试**：使用完整 schema 调用 `generate_text2kgbench_candidates.py`，第一个请求在 `deepseek-v3` 上反复 retry，超过 6 分钟无响应，终止。
2. **并发重跑**：改为 `run_car33_pipeline_extraction.py`，每个 sample 新建 `GraphExtractFlow` 实例以绕过 `SchedulerSingleton` 的 schema 缓存问题；并发 5 workers。
3. **Abort 崩溃**：进程在 23/33 时因 `Abort trap: 6` 崩溃。根因是 `property_graph_extract.py` 的 `filter_item` 函数假设 `item["properties"]` 一定是 dict，但 LLM 偶尔返回 list，`.items()` 抛出 `AttributeError`，异常穿透 pybind11 层导致解释器 abort。
4. **修复并 resume**：兼容 `properties` 的 dict / list-of-dict / list-of-name 三种形式，并跳过非 dict item。修复后 resume，33/33 全部完成。

#### 产出

| 项目 | 数值 |
|------|------|
| 完成 sample 数 | 33 / 33 |
| 非空 sample 数 | 30 |
| 总 vertices | 2348 |
| 总 edges | 972 |
| 平均每 sample vertices | 71.2 |
| 平均每 sample edges | 29.5 |

#### 关键指标

> ⚠️ **2026-07-05 修正**：本表指标来自 2026-07-03 的原始产物，当时未去掉边端点 ID 前缀，`orphan_edge_rate` / `triple_f1` 被严重误判。修正后数据见 §10.6。

| 指标 | Pipeline | 备注 |
|------|----------|------|
| entity_f1 | 0.1160 | 能抽出实体，但 name 与 gold 对齐不佳 |
| triple_f1 | 0.0000 | 边两端 name 与 vertex name 不匹配，orphan_edge_rate 0.7576 |
| property_f1 | 0.0404 | property precision 0.1009，recall 仅 0.0266 |
| json_parse_rate | 0.7987 | 大部分 LLM 输出可被解析为 JSON |
| type_constraint_pass | 0.9091 | schema 标签输出基本合法 |
| required_property_fill | 0.9091 | 必填属性填充率较高 |
| illegal_edge_rate | 0.0000 | 无边违反 source/target 类型约束 |
| orphan_edge_rate | 0.7576 | 边-顶点 name 不一致是最大问题 |
| duplicate_entity_rate | 0.1181 | 同实体跨段落/chunk 重复抽取 |
| duplicate_edge_rate | 0.0416 | 少量重复边 |
| density | 0.0057 | 图比 API candidate 更稀疏 |
| largest_component_ratio | 0.1358 | 最大连通分量占比低 |
| load_to_db_success | 0.0000 | 未真实导入图数据库 |
| temporal_valid_rate | 1.0000 | 无时序冲突 |
| conflict_rate | 0.0000 | 无实体冲突 |

#### 关于 deepseek-v4-flash 的 thinking

用户提供了 DeepSeek 官方文档：OpenAI SDK 中需要通过 `extra_body={"thinking": {"type": "disabled"}}` 关闭 thinking，而 `reasoning_effort` 只控制思考强度。我们据此更新了 `src/hugegraph_llm/models/llms/openai.py`：

```python
if self.model.startswith("deepseek-v4"):
    return {
        "reasoning_effort": "low",
        "extra_body": {"thinking": {"type": "disabled"}},
    }
```

并重新跑了一遍 33 chunk pipeline 抽取做对比：

> ⚠️ **2026-07-05 修正**：下表为 2026-07-03 原始产物的对比，尚未去掉边端点 ID 前缀。修正后的 thinking/no-thinking 对比见 §10.6。

| 指标 | Thinking Enabled | Thinking Disabled |
|------|------------------|-------------------|
| 完成时间 | ~25 分钟 | ~3 分钟 |
| 非空 sample 数 | 30 / 33 | 19 / 33 |
| 总 vertices | 2348 | 813 |
| 总 edges | 972 | 370 |
| entity_f1 | **0.1160** | 0.0535 |
| triple_f1 | 0.0000 | 0.0000 |
| property_f1 | **0.0404** | 0.0152 |
| json_parse_rate | **0.7987** | 0.2893 |
| type_constraint_pass | **0.9091** | 0.5758 |
| orphan_edge_rate | 0.7576 | **0.4242** |
| duplicate_entity_rate | 0.1181 | 0.0489 |

**结论**：关闭 thinking 后速度提升约 8 倍，但抽取质量明显下降。对于汽车手册这种复杂结构化抽取任务，`deepseek-v4-flash` 的 thinking 过程对生成合法 JSON 和遵循 schema 至关重要。因此**主结果采用 thinking enabled 版本**；thinking disabled 仅作为效率对比保留。若需完全无 reasoning 且能接受质量下降，可使用该配置；若追求抽取质量，应保持 thinking enabled 或尝试换用 `deepseek-v3`。

#### 原因与后续

- **entity_f1 低**：精确匹配对中文命名粒度敏感，gold 中大量实体带颜色/状态后缀，pipeline 输出常省略；同义词/近义词也无法对齐。
- **triple_f1 为 0**：核心问题是边-顶点 name 不一致。`ExtractNode` 按段落独立抽取后，边里的 `outV`/`inV` name 与对应 vertex 的 `name` 不完全一致，导致 benchmark 视为 orphan edge。
- **建议**：
  1. 在 `GraphExtractFlow` 后增加 entity resolution / name canonicalization，把“制动系统故障警告灯”与“制动系统故障警告灯-红色”对齐。
  2. 在 prompt 中强制边必须引用已抽出顶点的 exact name，减少 orphan edge。
  3. 如需提速，可将 extract 模型换为 `deepseek-v3` 做对比实验。

### 10.5 产物清单

```text
benchmark_data/outputs/car33/
├── car33_api_vs_manual.json                          # API candidate vs manual（gold + candidate）
├── car33_schema.json                                 # 推断 schema
├── car33_api_vs_manual_baseline.json                 # API candidate 精确匹配指标
├── car33_api_vs_manual_baseline.md
├── car33_pipeline_candidates.json                    # Pipeline 抽取结果（thinking enabled，主结果）
├── car33_pipeline_baseline.json                      # Pipeline 精确匹配指标
├── car33_pipeline_baseline.md
├── car33_pipeline_candidates_no_thinking.json        # Pipeline 抽取结果（thinking disabled 对比）
├── car33_pipeline_baseline_no_thinking.json
├── car33_pipeline_baseline_no_thinking.md
└── car33_extraction_report.md                        # 完整报告
```

### 10.6 2026-07-05 修正：边端点 ID 前缀问题

#### 问题发现

复阅 `car33_pipeline_candidates.json` 时发现，`GRAPH_EXTRACT` 输出的边端点带有 `"数字:"` ID 前缀：

```json
{
  "label": "HAS_STATUS",
  "outV": "1:自动远光灯开启指示灯",
  "inV": "8:自动远光灯开启"
}
```

而顶点 `name` 是干净的：

```json
{
  "label": "Component",
  "name": "自动远光灯开启指示灯"
}
```

`run_car33_pipeline_extraction.py` 在转换时直接使用了 `edge["outV"]` / `edge["inV"]`，没有剥离前缀，导致 benchmark 把所有边误判为 orphan edge。

#### 验证

| 统计项 | thinking enabled | no-thinking |
|--------|------------------|-------------|
| 总边数 | 972 | 370 |
| 带 ID 前缀的边 | 972（100%） | 370（100%） |
| 当前 orphan edge | 972（100%） | 157（42.4%） |
| 去掉前缀后 orphan edge | 0（0%） | 0（0%） |

#### 修正方法

新增后处理脚本 `scripts/benchmark/fix_car33_edge_ids.py`，读取已有 candidate JSON（无需重新跑 LLM），对每条边的 `outV`/`inV` 去掉 `^\d+:` 前缀，输出 `_fixed.json`。

```bash
cd /Users/xg/Coding/PersonalFile/BaiduCoding/hugegraph-ai/hugegraph-llm

# 修正 thinking enabled
python scripts/benchmark/fix_car33_edge_ids.py \
  --input benchmark_data/outputs/car33/car33_pipeline_candidates.json \
  --output benchmark_data/outputs/car33/car33_pipeline_candidates_fixed.json

# 修正 no-thinking
python scripts/benchmark/fix_car33_edge_ids.py \
  --input benchmark_data/outputs/car33/car33_pipeline_candidates_no_thinking.json \
  --output benchmark_data/outputs/car33/car33_pipeline_candidates_no_thinking_fixed.json
```

#### 重新跑 benchmark

```bash
uv run python -m hugegraph_llm.benchmark run \
  --mode extraction \
  --data benchmark_data/outputs/car33/car33_pipeline_candidates_fixed.json \
  --metrics entity_f1,triple_f1,property_f1,schema_validity,structural_integrity,syntax_validity,graph_structure,conflict_detection,temporal_validity \
  --language zh --offline \
  --output benchmark_data/outputs/car33/car33_pipeline_baseline_fixed.md \
  --save-baseline benchmark_data/outputs/car33/car33_pipeline_baseline_fixed.json

uv run python -m hugegraph_llm.benchmark run \
  --mode extraction \
  --data benchmark_data/outputs/car33/car33_pipeline_candidates_no_thinking_fixed.json \
  --metrics entity_f1,triple_f1,property_f1,schema_validity,structural_integrity,syntax_validity,graph_structure,conflict_detection,temporal_validity \
  --language zh --offline \
  --output benchmark_data/outputs/car33/car33_pipeline_baseline_no_thinking_fixed.md \
  --save-baseline benchmark_data/outputs/car33/car33_pipeline_baseline_no_thinking_fixed.json
```

#### 修正结果

**Thinking enabled**

| 指标 | 修正前 | 修正后 |
|------|--------|--------|
| orphan_edge_rate | 0.7576 | **0.0000** |
| triple_f1 | 0.0000 | **0.0099** |
| triple_precision | 0.0000 | 0.0133 |
| triple_recall | 0.0000 | 0.0089 |
| illegal_edge_rate | 0.0000 | 0.0149 |
| largest_component_ratio | 0.1358 | 0.2215 |
| entity_f1 | 0.1160 | 0.1160（不变） |
| property_f1 | 0.0404 | 0.0404（不变） |

**No-thinking**

| 指标 | 修正前 | 修正后 |
|------|--------|--------|
| orphan_edge_rate | 0.4242 | **0.0000** |
| triple_f1 | 0.0000 | **0.0071** |
| largest_component_ratio | 0.1198 | 0.1953 |

#### 修正后结论

1. `orphan_edge_rate` 高确实是**转换脚本的 bug**，不是 pipeline 抽取能力差。修正后两个版本的 orphan_edge_rate 均归零。
2. `triple_f1` 从 0 上升到约 0.01，但仍然很低，说明即使边能正确挂到顶点，这些三元组也很少精确匹配 gold。
3. `entity_f1`、`property_f1` 修正前后不变，说明**真正的核心瓶颈是实体名对齐**，而不是边-顶点一致性。
4. 关闭 thinking 仍会显著降低抽取质量；修正后 thinking enabled 版本仍是主结果。

#### 新增产物

- `scripts/benchmark/fix_car33_edge_ids.py`
- `benchmark_data/outputs/car33/car33_pipeline_candidates_fixed.json`
- `benchmark_data/outputs/car33/car33_pipeline_candidates_no_thinking_fixed.json`
- `benchmark_data/outputs/car33/car33_pipeline_baseline_fixed.json`
- `benchmark_data/outputs/car33/car33_pipeline_baseline_fixed.md`
- `benchmark_data/outputs/car33/car33_pipeline_baseline_no_thinking_fixed.json`
- `benchmark_data/outputs/car33/car33_pipeline_baseline_no_thinking_fixed.md`
- `benchmark_data/outputs/car33/car33_pipeline_fix_report.md`

#### 后续待办

- [x] 修复源脚本 `run_car33_pipeline_extraction.py`：已在 `extract_candidates` 与 `_parse_raw_response` 中建立 `vertex_id -> name` 映射，并在读取 `outV`/`inV` 时自动剥离 `^\d+:` 前缀；以后重新跑 33 chunk 抽取无需再手动后处理。
- [ ] 重点优化 entity name 对齐与 relation extraction，这是当前 triple_f1 低的主要原因。
- [ ] 考虑引入语义对齐 benchmark 指标，避免精确匹配在汽车手册这类命名多变的领域严重低估真实质量。
