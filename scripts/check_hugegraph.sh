#!/usr/bin/env bash
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail
expected_version=${1:?Expected server version is required}
container_id=${2:?HugeGraph service container ID is required}
image_id=$(docker inspect --format '{{.Image}}' "${container_id}")
docker image inspect --format 'Image ID: {{.Id}}; registry digests: {{json .RepoDigests}}' "${image_id}"

response=$(mktemp)
trap 'rm -f "${response}"' EXIT
curl --fail --silent --show-error --connect-timeout 5 --max-time 30 \
  --user "${HUGEGRAPH_USER:-admin}:${HUGEGRAPH_PASSWORD:-admin}" \
  "${HUGEGRAPH_URL:-http://127.0.0.1:8080}/versions" >"${response}"
cat "${response}"
python3 - "${response}" "${expected_version}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    actual = json.load(stream)["versions"]["core"]
if actual != sys.argv[2]:
    sys.exit(f"Expected HugeGraph Server {sys.argv[2]}, got {actual}; check the latest image publication")
print(f"\nVerified HugeGraph Server {actual}")
PY
