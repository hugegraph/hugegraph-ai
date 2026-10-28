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

import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check_hugegraph.sh"


class VersionHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"versions": {"version": "v1", "core": "1.8.0"}}).encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


class TestHugeGraphVersionCheck(unittest.TestCase):
    def test_api_version_is_not_mistaken_for_core_and_stale_images_fail(self):
        with HTTPServer(("127.0.0.1", 0), VersionHandler) as server, tempfile.TemporaryDirectory() as directory:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(worker.join)
            self.addCleanup(server.shutdown)
            docker = Path(directory) / "docker"
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "test-image-digest"\n')
            docker.chmod(0o755)
            env = {
                **os.environ,
                "PATH": directory + os.pathsep + os.environ["PATH"],
                "HUGEGRAPH_URL": f"http://127.0.0.1:{server.server_port}",
                "NO_PROXY": "127.0.0.1",
                "no_proxy": "127.0.0.1",
            }
            for expected, success in (("1.8.0", True), ("1.7.0", False)):
                result = subprocess.run(
                    ["bash", str(SCRIPT), expected, "test-container"],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(success, result.returncode == 0, result.stderr)
                self.assertIn('"version": "v1"', result.stdout)
                if not success:
                    self.assertIn("got 1.8.0", result.stderr)
