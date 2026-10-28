#! /bin/bash
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# Default developer tools: uv + Ruff + ty. -b/-p preserve the legacy
# formatting/lint selections; -t selects type checking.
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
FORMAT=false
LINT=false
TYPECHECK=false
while getopts ":bpt" opt; do
  case "${opt}" in
    b) FORMAT=true ;;
    p) LINT=true ;;
    t) TYPECHECK=true ;;
    *) echo "Usage: $0 [-b (format)] [-p (lint)] [-t (types)]" >&2; exit 2 ;;
  esac
done
if [ "${FORMAT}" = false ] && [ "${LINT}" = false ] && [ "${TYPECHECK}" = false ]; then
  FORMAT=true
  LINT=true
  TYPECHECK=true
fi
cd "${ROOT_DIR}"
if [ "${FORMAT}" = true ]; then
  uv run --extra dev ruff format .
fi
if [ "${LINT}" = true ]; then
  uv run --extra dev ruff check .
fi
if [ "${TYPECHECK}" = true ]; then
  uv run --extra dev ty check hugegraph-llm/src/hugegraph_llm hugegraph-python-client/src/pyhugegraph
fi