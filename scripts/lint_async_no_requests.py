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

"""
Phase 2 lint: forbid `requests.*` calls inside `async def` bodies.

grep misses async-nested defs, helper indirection, and inherited methods.
This AST visitor walks every `async def` in hugegraph-llm and reports any
attribute access whose root identifier is `requests`. White-listed files
(Gradio UI / startup config) are skipped because they are not on the request
hot path.

Usage:
    python scripts/lint_async_no_requests.py

Exit code 1 iff any violation found.
"""

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = REPO_ROOT / "hugegraph-llm" / "src" / "hugegraph_llm"

EXEMPT_SUFFIXES = {
    "hugegraph-llm/src/hugegraph_llm/demo/rag_demo/configs_block.py",
    "hugegraph-llm/src/hugegraph_llm/config/huge_config.py",
}


class AsyncRequestsChecker(ast.NodeVisitor):
    """Records every `requests.*` (or aliased) call inside an async function.

    First pass over the module collects all import-level bindings that point at
    the ``requests`` package — both module aliases (``import requests as req``)
    and symbol-level imports (``from requests import get, post as p``). The
    visit_Call path then resolves the call's root identifier against those
    bindings, so aliased / star-imported entry points no longer slip past the
    gate.
    """

    def __init__(self) -> None:
        self.errors: list[tuple[int, str]] = []
        self._depth = 0
        # Names bound to the requests module itself (via ``import requests`` /
        # ``import requests as X``).
        self._module_aliases: set[str] = set()
        # Names bound to symbols pulled directly out of requests (via
        # ``from requests import get`` / ``from requests import get as g``).
        self._symbol_aliases: set[str] = set()

    def collect_bindings(self, tree: ast.AST) -> None:
        """Pre-scan: register every alias that ultimately refers to ``requests``."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "requests" or alias.name.startswith("requests."):
                        self._module_aliases.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and (
                node.module == "requests" or (node.module is not None and node.module.startswith("requests."))
            ):
                for alias in node.names:
                    # ``from requests import *`` exposes every public symbol;
                    # we can't enumerate them here, so flag the import itself.
                    if alias.name == "*":
                        self.errors.append((node.lineno, "from requests import *"))
                        continue
                    self._symbol_aliases.add(alias.asname or alias.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._depth += 1
        try:
            self.generic_visit(node)
        finally:
            self._depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        if self._depth > 0:
            root = node.func
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and (root.id in self._module_aliases or root.id in self._symbol_aliases):
                try:
                    snippet = ast.unparse(node.func)
                except AttributeError:
                    snippet = "<unparsable>"
                self.errors.append((node.lineno, snippet))
        self.generic_visit(node)


def _normalize(path: Path) -> str:
    return str(path).replace("\\", "/")


def check_file(path: Path) -> list[tuple[Path, int, str]]:
    rel = _normalize(path.relative_to(REPO_ROOT))
    if any(rel.endswith(suffix) for suffix in EXEMPT_SUFFIXES):
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        print(f"{path}: skipped (syntax error: {e})", file=sys.stderr)
        return []
    checker = AsyncRequestsChecker()
    checker.collect_bindings(tree)
    checker.visit(tree)
    return [(path, ln, call) for ln, call in checker.errors]


def main() -> int:
    if not TARGET_DIR.exists():
        print(f"target dir not found: {TARGET_DIR}", file=sys.stderr)
        return 1
    violations = []
    for py_file in sorted(TARGET_DIR.rglob("*.py")):
        violations.extend(check_file(py_file))
    if not violations:
        print("OK: no `requests.*` calls inside async functions.")
        return 0
    for path, line, call in violations:
        print(f"{path}:{line}: async function calls forbidden `{call}`")
    print(f"\n{len(violations)} violation(s) found.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
