# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Smoke-test the normal LLM application against a local OpenAI HTTP fixture.

Run inside a disposable container with the normal application already started:

    docker cp docker/tests/smoke_llm.py llm-smoke:/tmp/smoke_llm.py
    docker exec llm-smoke python /tmp/smoke_llm.py

Use ENABLE_LOGIN=false, GRAPH_URL=http://127.0.0.1:9,
GRADIO_ANALYTICS_ENABLED=false, NO_PROXY=127.0.0.1,localhost,
HUGEGRAPH_LLM_ENV_PATH=/tmp/llm-smoke.env and
HUGEGRAPH_LLM_PROMPT_CONFIG_PATH=/tmp/llm-smoke-prompts.yaml at startup.
This test updates the application's LLM configuration to synthetic credentials.
It uses no HugeGraph server or external model service. Schema design has no
dedicated application HTTP route, so it exercises the installed SDK using the
same real provider HTTP transport as the application's extraction routes.
"""

import argparse
import asyncio
import ipaddress
import json
import os
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from hugegraph_llm_sdk import design_schema
from hugegraph_llm_sdk.providers.openai import OpenAIClient

SOURCE = "Alice is a software engineer who works for Acme."
SCHEMA = {
    "vertexlabels": [
        {
            "id": 1,
            "name": "person",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["name"],
            "properties": ["name", "occupation"],
            "nullable_keys": [],
        },
        {
            "id": 2,
            "name": "company",
            "id_strategy": "PRIMARY_KEY",
            "primary_keys": ["name"],
            "properties": ["name"],
            "nullable_keys": [],
        },
    ],
    "edgelabels": [{"name": "works_for", "source_label": "person", "target_label": "company", "properties": []}],
    "propertykeys": [
        {"name": "name", "data_type": "TEXT", "cardinality": "SINGLE"},
        {"name": "occupation", "data_type": "TEXT", "cardinality": "SINGLE"},
    ],
}


def graph(occupation="software engineer"):
    # Aliases deliberately require the shared normalization code to fix IDs
    # and both edge endpoints before the result can pass the assertions.
    return {
        "vertices": [
            {"id": "Alice", "label": "person", "properties": {"name": "Alice", "occupation": occupation}},
            {"id": "Acme", "label": "company", "properties": {"name": "Acme"}},
        ],
        "edges": [
            {
                "label": "works_for",
                "outV": "Alice",
                "outVLabel": "person",
                "inV": "Acme",
                "inVLabel": "company",
                "properties": {},
            }
        ],
    }


class OpenAIFixture(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), OpenAIHandler)
        self.calls = Counter()
        self.errors = []
        self.lock = threading.Lock()

    def completion(self, prompt):
        if prompt == "test":
            stage, result = "config_probe", "ok"
        elif prompt.startswith("SMOKE_SCHEMA\n"):
            stage, result = "schema", SCHEMA
        elif prompt.startswith("SMOKE_LEGACY\n"):
            stage, result = "legacy_extract", graph()
        elif prompt.startswith("SMOKE_REVIEWED\n"):
            stage, result = "reviewed_extract", graph("pilot")
        elif "\n## Input\n" in prompt:
            context = json.loads(prompt.rsplit("\n## Input\n", 1)[1])
            if "issues" in context:
                stage, result = "repair", graph()
            else:
                stage = "review"
                person = next(vertex for vertex in context["graph"]["vertices"] if vertex["label"] == "person")
                if person["properties"]["occupation"] == "software engineer":
                    result = {"decision": "pass", "issues": []}
                else:
                    result = {
                        "decision": "fix",
                        "issues": [
                            {
                                "path": "vertices[0].properties.occupation",
                                "message": "The occupation does not match the source.",
                                "evidence": SOURCE,
                            }
                        ],
                    }
        else:
            raise ValueError("Unexpected model prompt")
        with self.lock:
            self.calls[stage] += 1
        return result if isinstance(result, str) else json.dumps(result)


class OpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            content = self.server.completion(request["messages"][-1]["content"])
            result = {
                "id": "chatcmpl-local-smoke",
                "object": "chat.completion",
                "created": 1,
                "model": request["model"],
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            with self.server.lock:
                self.server.errors.append(type(exc).__name__ + ": " + str(exc))
            self.send_error(500, "Local fixture rejected the request")

    def log_message(self, _format, *args):
        pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def request_http(app_url, path, body=None):
    request = Request(
        app_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    # Never send loopback traffic through an inherited corporate proxy.
    with build_opener(ProxyHandler({})).open(request, timeout=60) as response:
        return response.status, response.read().decode()


def wait_for_app(app_url, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            status, body = request_http(app_url, "/")
            require(status == 200 and "gradio" in body.lower(), "The normal Gradio homepage did not load")
            return
        except (OSError, URLError):
            if time.monotonic() >= deadline:
                raise RuntimeError("The application did not start before the timeout") from None
            time.sleep(1)


def check_graph(result):
    vertices, edges = result["vertices"], result["edges"]
    require(len(vertices) == 2 and len(edges) == 1, "Expected two vertices and one edge")
    require({vertex["id"] for vertex in vertices} == {"1:Alice", "2:Acme"}, "Vertex IDs were not normalized")
    person = next(vertex for vertex in vertices if vertex["label"] == "person")
    require(person["properties"]["occupation"] == "software engineer", "The incorrect occupation was not repaired")
    edge = edges[0]
    require(
        (edge["label"], edge["outV"], edge["inV"]) == ("works_for", "1:Alice", "2:Acme"),
        "The relationship or its normalized endpoints are incorrect",
    )


def run(app_url, startup_timeout):
    wait_for_app(app_url, startup_timeout)
    server = OpenAIFixture()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    model = None
    try:
        api_base = f"http://127.0.0.1:{server.server_port}/v1"
        status, _ = request_http(
            app_url,
            "/config/llm",
            {
                "llm_type": "openai",
                "api_key": "local-smoke-no-secret",
                "api_base": api_base,
                "language_model": "gpt-4.1-mini",
                "max_tokens": "4096",
            },
        )
        require(status == 201, "The LLM configuration endpoint failed")
        model = OpenAIClient(api_key="local-smoke-no-secret", api_base=api_base, model_name="gpt-4.1-mini")
        draft = design_schema(
            SOURCE,
            model=model,
            questions=["Where does Alice work?"],
            prompt="SMOKE_SCHEMA\n{raw_texts}\n{query_examples}\n{few_shot_schema}",
        )
        require(draft.schema == SCHEMA and not draft.issues, "Schema design or validation failed")
        request = {
            "texts": [SOURCE],
            "schema": draft.schema,
            "extract_type": "property_graph",
            "language": "en",
            "split_type": "document",
            "include_meta": True,
            "example_prompt": "SMOKE_LEGACY\n",
        }
        status, body = request_http(app_url, "/graph/extract", request)
        legacy = json.loads(body)
        require(status == 200 and legacy["status"] == "succeeded", "Legacy extraction failed")
        require("chunk_results" not in legacy, "Legacy extraction unexpectedly enabled review")
        check_graph(legacy["result"])

        request.update(example_prompt="SMOKE_REVIEWED\n", review_options={})
        status, body = request_http(app_url, "/graph/extract", request)
        reviewed = json.loads(body)
        require(status == 200 and reviewed["status"] == "succeeded", f"Reviewed extraction failed: {reviewed}")
        check_graph(reviewed["result"])
        require(reviewed["meta"] == {"vertex_count": 2, "edge_count": 1, "text_count": 1}, "Unexpected metadata")
        chunks = reviewed["chunk_results"]
        require(len(chunks) == 1 and chunks[0]["status"] == "final", "The reviewed chunk did not become final")
        require(
            (chunks[0]["reviews_used"], chunks[0]["fixes_used"], chunks[0]["llm_calls"]) == (2, 1, 4),
            "The review, repair and second review did not all execute",
        )
        expected = {
            "config_probe": 1,
            "schema": 1,
            "legacy_extract": 1,
            "reviewed_extract": 1,
            "review": 2,
            "repair": 1,
        }
        require(dict(server.calls) == expected, f"Unexpected model HTTP calls: {dict(server.calls)}")
        require(not server.errors, f"The local model fixture had errors: {server.errors}")
        return {
            "status": "passed",
            "gradio_homepage": "passed",
            "sdk_schema_design": "passed",
            "http_legacy_extraction": "passed",
            "http_review_repair": "passed",
            "vertices": len(reviewed["result"]["vertices"]),
            "edges": len(reviewed["result"]["edges"]),
            "model_http_calls": dict(server.calls),
        }
    finally:
        try:
            if model is not None:
                asyncio.run(model.aclose())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-url", default="http://127.0.0.1:8001")
    parser.add_argument("--startup-timeout", type=float, default=90)
    args = parser.parse_args()
    app_url = args.app_url.rstrip("/")
    parsed = urlsplit(app_url)
    if parsed.scheme != "http" or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        parser.error("--app-url must be an HTTP loopback origin")
    try:
        is_loopback = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        parser.error("--app-url must address this disposable container's loopback interface")
    # The SDK also creates HTTP transports, so exempt loopback from proxying.
    no_proxy = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = no_proxy + ",127.0.0.1,localhost"
    try:
        print(json.dumps(run(app_url, args.startup_timeout), indent=2))  # noqa: T201
    except HTTPError as exc:
        raise SystemExit(f"Application HTTP {exc.code}: {exc.read().decode()}") from exc


if __name__ == "__main__":
    main()
