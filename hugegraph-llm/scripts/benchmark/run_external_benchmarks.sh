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

# Run smoke benchmark over all prepared external datasets.
# This script does not require an LLM (--offline) and uses the default 20-sample
# JSON files produced by prepare_external_datasets.py.

set -euo pipefail

# Resolve the repository root robustly. Prefer git; fall back to the script's
# location so the script still works in a shallow export.
if git rev-parse --show-toplevel >/dev/null 2>&1; then
    REPO_ROOT="$(git rev-parse --show-toplevel)"
else
    REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
fi
cd "$REPO_ROOT"

# Activate the project virtualenv if it exists and no active venv is present.
if [[ -z "${VIRTUAL_ENV:-}" && -f .venv/bin/activate ]]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

BENCHMARK=(python -m hugegraph_llm.benchmark run)
DATA_DIR="hugegraph-llm/benchmark_data/external"

run_retrieval() {
    local name="$1"
    local lang="$2"
    local file="$DATA_DIR/${name}_retrieval.json"
    if [[ ! -f "$file" ]]; then
        echo "SKIP: $file not found"
        return
    fi
    echo "==> Running retrieval benchmark: $name"
    "${BENCHMARK[@]}" --mode retrieval --data "$file" --language "$lang" --offline
    echo ""
}

run_extraction() {
    local file="$1"
    if [[ ! -f "$file" ]]; then
        echo "SKIP: $file not found"
        return
    fi
    echo "==> Running extraction benchmark: $file"
    "${BENCHMARK[@]}" --mode extraction --data "$file" --language en --offline
    echo ""
}

# ---------------------------------------------------------------------------
# Retrieval datasets
# ---------------------------------------------------------------------------
run_retrieval hotpotqa en
run_retrieval 2wikimultihopqa en
run_retrieval musique en
run_retrieval anonyrag_chs zh
run_retrieval anonyrag_eng en
run_retrieval graphrag_bench_medical en
run_retrieval graphrag_bench_novel en

# ---------------------------------------------------------------------------
# Extraction datasets (run the movie domain as the smoke example)
# ---------------------------------------------------------------------------
run_extraction "$DATA_DIR/text2kgbench_movie_extraction.json"

echo "All smoke benchmarks finished."
