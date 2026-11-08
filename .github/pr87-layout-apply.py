from pathlib import Path
import subprocess

root = Path.cwd()
old, new = 'graphrag/eval', 'hugegraph-llm-sdk/eval'
path = root / 'scripts/tests/test_ci.py'
text = path.read_text().replace(old, new)
text = text.replace(
    '            "hugegraph-llm-sdk/eval/README.md",\n',
    '            "hugegraph-llm-sdk/eval/README.md",\n'
    '            "hugegraph-llm-sdk/eval/pyproject.toml",\n'
    '            "hugegraph-llm-sdk/eval/tests/test_samples.py",\n'
    '            "hugegraph-llm-sdk/eval/examples/basic.py",\n',
)
text = text.replace(
    '    def test_full_runtimes_cover_python_312_through_314(self):',
    '''    def test_nested_package_changes_do_not_hide_parent_changes(self):
        self.assert_modules(
            ["hugegraph-llm-sdk/eval/README.md", "hugegraph-llm-sdk/src/hugegraph_llm_sdk/api.py"],
            {"sdk", "eval", "llm"},
        )
        self.assert_modules(["hugegraph-llm-sdk/evaluation.py"], {"sdk", "llm"})

    def test_full_runtimes_cover_python_312_through_314(self):''',
)
path.write_text(text)

for rel in subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines():
    path = root / rel
    try:
        text = path.read_text()
    except UnicodeError:
        continue
    updated = text.replace(old, new)
    if rel == 'pyproject.toml':
        updated = updated.replace('graphrag/*/', new + '/')
    if text != updated:
        path.write_text(updated)
(root / old).rename(root / new)
(root / 'graphrag').rmdir()


def replace(relative: str, before: str, after: str) -> None:
    path = root / relative
    text = path.read_text()
    assert text.count(before) == 1, (relative, before, text.count(before))
    path.write_text(text.replace(before, after))


replace('scripts/ci.py',
'''        in_module = any(path.startswith(module + "/") for module in MODULES.values())
        if is_documentation and not in_module:''',
'''        owners = [key for key, module in MODULES.items() if path.startswith(module + "/")]
        owner = max(owners, key=lambda key: len(MODULES[key]), default=None)
        if is_documentation and owner is None:''')
replace('scripts/ci.py',
'''        for key, module in MODULES.items():
            if path.startswith(module + "/") or path == f".github/workflows/{WORKFLOWS[key]}":
                flags[key] = True''',
'''        if owner is not None:
            flags[owner] = True
        for key, workflow in WORKFLOWS.items():
            if path == f".github/workflows/{workflow}":
                flags[key] = True''')

replace('hugegraph-llm-sdk/README.md', '## 安装到另一个项目',
'''## 目录与包边界

本目录保留抽取 SDK 的 `src/hugegraph_llm_sdk/`，并在 [eval/](eval/README.md)
存放独立评测 SDK。两者分别拥有 `pyproject.toml`，由仓库根 workspace 管理；
`eval/` 不属于 `hugegraph_llm_sdk` 命名空间，也不随本包的 wheel 或源码包分发。
评测包的发行名是 `hugegraph-llm-eval`，导入名是 `hugegraph_llm_eval`，可单独安装。
抽取 SDK 或应用需要评测时，通过评测包的公开输入和结果契约按需接入；本次目录调整
不增加隐式依赖，也不改变抽取或评测 API。

## 安装到另一个项目''')
replace(new + '/README.md', '## Install',
'''## Package boundary

The package lives at `hugegraph-llm-sdk/eval/` to keep the repository layout compact.
It has its own `pyproject.toml` and remains a separate root-workspace member:
`hugegraph-llm-eval` is the distribution and `hugegraph_llm_eval` is the import name.
It is not a submodule of `hugegraph_llm_sdk` and is not bundled with the extraction
SDK. External projects can install it independently; extraction or application
code can opt in through its public contracts without a reverse dependency.

## Install''')
replace('docs/sdk/architecture.md',
'''评测能力位于 `hugegraph-llm-sdk/eval/`：抽取、检索与答案的评分规则、Judge 协议和执行语义都只在该包内维护。''',
'''独立评测 SDK 存放在 `hugegraph-llm-sdk/eval/`，具有自己的 `pyproject.toml` 和
`hugegraph_llm_eval` 命名空间，不包含在抽取 SDK 的发行包中。两者在根 workspace 中分别注册。
抽取 SDK 可按需通过评测包的公开契约接入，评测包不得反向依赖抽取 SDK 或应用。
抽取、检索与答案的评分规则、Judge 协议和执行语义都只在评测包内维护。''')
replace('docs/sdk/eval-architecture.md',
'''hugegraph-llm-sdk/ 负责把文本变成图（schema 设计 + 抽取）
hugegraph-llm-sdk/eval/    负责判断图、检索和答案的质量（本包）
hugegraph-llm/    负责把这些能力串成流程，并持有配置、持久化、报告和 UI''',
'''hugegraph-llm-sdk/src/   抽取 SDK：schema 设计 + 抽取
hugegraph-llm-sdk/eval/  独立评测 SDK：图、检索和答案的质量度量
hugegraph-llm/          应用：流程、配置、持久化、报告和 UI''')
replace('docs/sdk/eval-architecture.md',
'''因此评测包既可以被外部项目单独安装使用，也可以被 GraphRAG 流程嵌入''',
'''目录嵌套仅用于组织源码：抽取包与评测包各有 `pyproject.toml`，是根 workspace 的两个独立成员。
父包只分发自己的 `src/hugegraph_llm_sdk/` 和示例，评测包独立分发 `src/hugegraph_llm_eval/`。
抽取 SDK 可按需调用评测 SDK，评测 SDK 不反向导入抽取代码；本次迁移不增加默认运行时依赖。

因此评测包既可以被外部项目单独安装使用，也可以被 GraphRAG 流程嵌入''')
replace('docs/quality/ci.md',
'''SDK changes run the SDK distribution contracts and downstream LLM adapter tests,''',
'''The nested `hugegraph-llm-sdk/eval/` package is selected by the longest matching
module path. Eval-only changes do not select the extraction SDK or application;
changes to both packages select both suites. The SDK distribution smoke also
checks the built wheel and sdist for accidentally bundled eval sources.

SDK changes run the SDK distribution contracts and downstream LLM adapter tests,''')
replace('AGENTS.md',
'''- `hugegraph-llm-sdk/eval/` owns the standalone evaluation runtime:''',
'''- `hugegraph-llm-sdk/eval/` is a separate workspace package, not part of the extraction SDK distribution. It owns the standalone evaluation runtime:''')

parent_project = root / 'hugegraph-llm-sdk/pyproject.toml'
parent_project.write_text(parent_project.read_text() + '''
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--strict-markers --strict-config"
''')

replace('hugegraph-llm-sdk/tests/distribution_smoke.py',
'''import sys
from pathlib import Path''',
'''import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath''')
replace('hugegraph-llm-sdk/tests/distribution_smoke.py',
'''    "hugegraph_llm_core",
''',
'''    "hugegraph_llm_core",
    "hugegraph_llm_eval",
''')
replace('hugegraph-llm-sdk/tests/distribution_smoke.py',
'''def verify_distribution():''',
'''def verify_archive(path: Path) -> None:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = [PurePosixPath(name) for name in archive.namelist()]
        required = PurePosixPath("hugegraph_llm_sdk/__init__.py")
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path) as archive:
            names = [PurePosixPath(*PurePosixPath(name).parts[1:]) for name in archive.getnames()]
        required = PurePosixPath("src/hugegraph_llm_sdk/__init__.py")
    else:
        raise ValueError(f"unsupported distribution archive: {path}")
    assert required in names, f"{path.name} is missing {required}"
    for name in names:
        assert "hugegraph_llm_eval" not in name.parts, f"{path.name} bundles the eval import package: {name}"
        assert not name.parts or name.parts[0] != "eval", f"{path.name} bundles the nested eval project: {name}"


def verify_distribution():''')
replace('hugegraph-llm-sdk/tests/distribution_smoke.py',
'''if __name__ == "__main__":
    run()''',
'''if __name__ == "__main__":
    for archive_path in sys.argv[1:]:
        verify_archive(Path(archive_path))
    run()''')
replace('.github/workflows/hugegraph-llm-sdk.yml',
'''            "$RUNNER_TEMP/sdk-venv-$format/bin/python" -B "$RUNNER_TEMP/sdk-build/tests/distribution_smoke.py"''',
'''            "$RUNNER_TEMP/sdk-venv-$format/bin/python" -B "$RUNNER_TEMP/sdk-build/tests/distribution_smoke.py" \\
              "$RUNNER_TEMP"/sdk-dist/*.$format''')

header = (root/'hugegraph-llm-sdk/tests/distribution_smoke.py').read_text().split('"""',1)[0]
(root/'hugegraph-llm-sdk/tests/test_distribution_archives.py').write_text(header + '''"""The extraction distribution must not include the nested evaluation package."""

import io
import tarfile
import zipfile

import pytest
from distribution_smoke import verify_archive


def _archive(tmp_path, format, extra=()):
    path = tmp_path / f"hugegraph_llm_sdk-1.8.0.{format}"
    if format == "whl":
        with zipfile.ZipFile(path, "w") as archive:
            for name in ("hugegraph_llm_sdk/__init__.py", *extra):
                archive.writestr(name, b"")
    else:
        with tarfile.open(path, "w:gz") as archive:
            for name in ("src/hugegraph_llm_sdk/__init__.py", *extra):
                info = tarfile.TarInfo(f"hugegraph_llm_sdk-1.8.0/{name}")
                archive.addfile(info, io.BytesIO(b""))
    return path


@pytest.mark.parametrize("format", ("whl", "tar.gz"))
def test_extraction_archives_remain_independent(tmp_path, format):
    verify_archive(_archive(tmp_path, format))


@pytest.mark.parametrize("format", ("whl", "tar.gz"))
@pytest.mark.parametrize(
    "leaked_path",
    ("eval/pyproject.toml", "eval/src/hugegraph_llm_eval/__init__.py", "hugegraph_llm_eval/__init__.py"),
)
def test_distribution_guard_rejects_nested_eval_sources(tmp_path, format, leaked_path):
    with pytest.raises(AssertionError, match="bundles"):
        verify_archive(_archive(tmp_path, format, (leaked_path,)))


def test_distribution_guard_rejects_missing_extraction_package(tmp_path):
    path = tmp_path / "wrong.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other/__init__.py", b"")
    with pytest.raises(AssertionError, match="missing"):
        verify_archive(path)
''')

replace('hugegraph-llm-sdk/pyproject.toml',
    'include = ["src/hugegraph_llm_sdk", "README.md", "LICENSE", "NOTICE", "examples"]',
    'include = ["/src/hugegraph_llm_sdk", "/README.md", "/LICENSE", "/NOTICE", "/examples"]\nexclude = ["/eval"]')
