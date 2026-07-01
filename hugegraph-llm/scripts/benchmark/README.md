# 外部数据集 Benchmark 输入格式

本目录的脚本把公开数据集转换为 HugeGraph-AI benchmark 的输入文件。
转换原则：**只使用原始数据集中已有的字段，不额外生成候选结果**。

- Retrieval：`gold_docs` 来自数据集自带的 supporting facts / evidence；
  `retrieved_docs` 来自数据集自带的 context / corpus（不是完美的 gold candidate）。
- Extraction（仅 Text2KGBench）：`gold_vertices` / `gold_edges` 来自 ground truth；
  `candidate_*` 字段为空，需要接入真实抽取 pipeline 后再跑 benchmark。
- Ablation：这些数据集均不提供 `raw / vector_only / graph_only / graph_vector` 四种答案，
  因此不自动生成 ablation 输入。

## 目录约定

文件按职责分开存放：

| 类型 | 位置 | 说明 |
|------|------|------|
| 数据准备库 | `src/hugegraph_llm/benchmark/datasets/prepare_external_datasets.py` | 可 import 的转换函数，被单测覆盖 |
| 入口脚本 | `scripts/benchmark/run_*.sh`、`run_hotpotqa_*_demo.py` | 批量跑 / demo |
| 原始公开数据缓存 | `benchmark_data/raw/`（已 gitignore） | 可由 `--download` 自动填充 |
| 生成的 JSON / 实验产物 | `benchmark_data/external/`（已 gitignore，不进版本库与 wheel） | 由脚本生成 |

## 数据根目录

脚本默认从项目内缓存目录 `hugegraph-llm/benchmark_data/raw/` 读取原始数据。对已登记公开来源的数据集，可加
`--download` 自动下载并缓存原始文件。

可通过以下方式覆盖：

```bash
# 环境变量
export EXTERNAL_DATASET_ROOT=/path/to/raw-public-datasets

# 或命令行参数
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset all --subset-size 20 \
  --data-root /path/to/raw-public-datasets

# 或使用更贴近缓存语义的别名
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset graphrag-bench --download \
  --cache-dir /path/to/raw-public-datasets
```

## 生成方式

```bash
cd /path/to/hugegraph-ai
source .venv/bin/activate

# 生成全部数据集的 smoke 版本（每个数据集前 20 条，可直接跑通）
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset all --subset-size 20

# 自动下载已登记来源的数据集，再生成 smoke 版本
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset graphrag-bench --download --subset-size 20

# 生成单个数据集全量
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset hotpotqa

# 生成 Text2KGBench 全量（10 个领域）
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets \
  --dataset text2kgbench
```

默认输出到 `hugegraph-llm/benchmark_data/external/`；可用 `--output-dir` 覆盖。

## 已生成文件

| 文件 | 数据集 | mode | 语言 | 说明 |
|------|--------|------|------|------|
| `hotpotqa_retrieval.json` | HotpotQA | retrieval | en | 多跳 QA 召回评测 |
| `2wikimultihopqa_retrieval.json` | 2WikiMultihopQA | retrieval | en | 多跳 QA 召回评测 |
| `musique_retrieval.json` | MuSiQue | retrieval | en | 多跳 QA 召回评测 |
| `anonyrag_chs_retrieval.json` | AnonyRAG | retrieval | zh | 中文匿名化推理（原始数据无 gold chunk/retrieved docs，均为空） |
| `anonyrag_eng_retrieval.json` | AnonyRAG | retrieval | en | 英文匿名化推理（同上） |
| `graphrag_bench_medical_retrieval.json` | GraphRAG-Bench | retrieval | en | 医学领域 QA |
| `graphrag_bench_novel_retrieval.json` | GraphRAG-Bench | retrieval | en | 小说领域 QA |
| `text2kgbench_\<domain\>_extraction.json` | Text2KGBench | extraction | en | 10 个领域图抽取 gold 标注（candidate 为空） |

## 直接运行 benchmark

### 一键跑全部 smoke 评测

```bash
bash hugegraph-llm/scripts/benchmark/run_external_benchmarks.sh
```

### 单独运行

```bash
cd /path/to/hugegraph-ai
source .venv/bin/activate

# retrieval
python -m hugegraph_llm.benchmark run \
  --mode retrieval \
  --data hugegraph-llm/benchmark_data/external/hotpotqa_retrieval.json \
  --language en --offline

# Text2KGBench extraction（以 movie 为例）
python -m hugegraph_llm.benchmark run \
  --mode extraction \
  --data hugegraph-llm/benchmark_data/external/text2kgbench_movie_extraction.json \
  --language en --offline
```

## 全量数据

去掉 `--subset-size` 即可生成全量数据：

```bash
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets --dataset hotpotqa
python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets --dataset graphrag-bench-medical
```

注意：GraphRAG-Bench 全量 context 较大，生成的 JSON 也会比较大，建议在需要时再生成。

## 接入真实 pipeline

当前文件只做了格式转换，retrieval 的 `retrieved_docs` 和 extraction 的 `candidate_*`
都是数据集原始内容或空列表。若要用 HugeGraph-AI pipeline 生成真实候选结果，可以：

1. 读取 `benchmark_data/external/` 下生成的 JSON；
2. 调用 `GraphExtractFlow` / `RAGGraphVectorFlow` 等节点生成 `candidate_vertices`、
   `candidate_edges` 或 `retrieved_docs`；
3. 写回 JSON 后再跑 `python -m hugegraph_llm.benchmark run`。

这样即可在不改动 benchmark 代码的前提下完成端到端评测。
