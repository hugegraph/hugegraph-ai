#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# Reproducible benchmark experiment on the smaller downloaded public datasets.
# Outputs: raw baseline JSONs, a Markdown report, and a combined log file.

set -euo pipefail

# Resolve repo root robustly.
if git rev-parse --show-toplevel >/dev/null 2>&1; then
    REPO_ROOT="$(git rev-parse --show-toplevel)"
else
    REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
fi
cd "$REPO_ROOT"

# Activate venv if present and not already active.
if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

COMMIT_HASH="$(git rev-parse --short HEAD)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
EXPERIMENT_DIR="hugegraph-llm/benchmark_data/external/experiments/small_datasets_${TIMESTAMP}"
mkdir -p "$EXPERIMENT_DIR"

export COMMIT_HASH EXPERIMENT_DIR

LOG_FILE="$EXPERIMENT_DIR/experiment.log"
REPORT_FILE="$EXPERIMENT_DIR/report.md"
DATA_DIR="hugegraph-llm/benchmark_data/external"
PREPARE=(python -m hugegraph_llm.benchmark.datasets.prepare_external_datasets)
BENCHMARK=(python -m hugegraph_llm.benchmark run)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

run_cmd() {
    echo "" >> "$LOG_FILE"
    echo "\$ $*" >> "$LOG_FILE"
    "$@" 2>&1 | tee -a "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# 1. Prepare full datasets for the smaller public datasets.
# ---------------------------------------------------------------------------
log "Experiment started"
log "Commit: $COMMIT_HASH"
log "Results directory: $EXPERIMENT_DIR"
log "Preparing small public datasets (full, no subset)..."

for dataset in hotpotqa 2wikimultihopqa musique anonyrag-chs anonyrag-eng; do
    log "Preparing $dataset"
    run_cmd "${PREPARE[@]}" --dataset "$dataset"
done

log "Preparing Text2KGBench (all 10 domains, full)"
run_cmd "${PREPARE[@]}" --dataset text2kgbench

# ---------------------------------------------------------------------------
# 2. Run retrieval benchmarks.
# ---------------------------------------------------------------------------
log "Running retrieval benchmarks..."

run_retrieval() {
    local name="$1"
    local lang="$2"
    local data_file="$DATA_DIR/${name}_retrieval.json"
    local baseline="$EXPERIMENT_DIR/${name}_retrieval_baseline.json"
    log "Retrieval benchmark: $name"
    run_cmd "${BENCHMARK[@]}" --mode retrieval --data "$data_file" --language "$lang" --offline --save-baseline "$baseline"
}

run_retrieval hotpotqa en
run_retrieval 2wikimultihopqa en
run_retrieval musique en
run_retrieval anonyrag_chs zh
run_retrieval anonyrag_eng en

# ---------------------------------------------------------------------------
# 3. Run extraction benchmarks on the smaller Text2KGBench domains.
# ---------------------------------------------------------------------------
log "Running extraction benchmarks..."

for domain in culture movie music sport book military computer space politics nature; do
    data_file="$DATA_DIR/text2kgbench_${domain}_extraction.json"
    baseline="$EXPERIMENT_DIR/text2kgbench_${domain}_extraction_baseline.json"
    log "Extraction benchmark: text2kgbench $domain"
    run_cmd "${BENCHMARK[@]}" --mode extraction --data "$data_file" --language en --offline --save-baseline "$baseline"
done

# ---------------------------------------------------------------------------
# 4. Generate Markdown report.
# ---------------------------------------------------------------------------
log "Generating report..."

python3 - <<'PY'
import json
import os
from pathlib import Path

exp_dir = Path(os.environ["EXPERIMENT_DIR"])
commit = os.environ["COMMIT_HASH"]

def load_baseline(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def fmt_metrics(metrics: dict):
    lines = ["| Metric | Score |", "|--------|-------|"]
    for k, v in sorted(metrics.items()):
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)

lines = []
lines.append("# Small Public Datasets Benchmark Report")
lines.append("")
lines.append(f"- **Commit**: `{commit}`")
lines.append(f"- **Timestamp**: {exp_dir.name.split('_')[-1]}")
lines.append("- **Mode**: offline (no LLM)")
lines.append("")
lines.append("## Retrieval results")
lines.append("")

retrieval_files = sorted(exp_dir.glob("*_retrieval_baseline.json"))
for f in retrieval_files:
    data = load_baseline(f)
    name = f.stem.replace("_retrieval_baseline", "")
    lines.append(f"### {name}")
    lines.append(f"- Samples: {data.get('sample_count', 'N/A')}")
    lines.append("")
    lines.append(fmt_metrics(data.get("overall", {})))
    lines.append("")

lines.append("## Extraction results")
lines.append("")

extraction_files = sorted(exp_dir.glob("text2kgbench_*_extraction_baseline.json"))
for f in extraction_files:
    data = load_baseline(f)
    name = f.stem.replace("_extraction_baseline", "")
    lines.append(f"### {name}")
    lines.append(f"- Samples: {data.get('sample_count', 'N/A')}")
    lines.append("")
    lines.append(fmt_metrics(data.get("overall", {})))
    lines.append("")

lines.append("## Reproduction")
lines.append("")
lines.append("Run the following from the repository root:")
lines.append("")
lines.append("```bash")
lines.append("bash hugegraph-llm/scripts/benchmark/run_small_datasets_experiment.sh")
lines.append("```")
lines.append("")
lines.append("The script regenerates the input JSONs, runs all benchmarks offline, and writes")
lines.append("baselines + this report into a timestamped `experiments/small_datasets_*/` directory.")
lines.append("")

report_path = exp_dir / "report.md"
report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"Report written to {report_path}")
PY

log "Experiment finished. Report: $REPORT_FILE"
echo ""
echo "Results are in: $EXPERIMENT_DIR"
