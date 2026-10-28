# Preparing a release

The root `pyproject.toml` owns `project.version` and the image configuration under
`tool.hugegraph.release`. Subpackage versions remain static so each wheel/sdist
can be built independently and the shared publisher can read their metadata.
MCP initialization and LLM OpenAPI report the installed distribution version,
so they follow the same source without another runtime version constant.

With Python 3.11+ at the repository root:

```bash
# Edit only the root release version, then synchronize generated fields.
python3.11 scripts/version.py sync
python3.11 scripts/version.py check
python3.11 scripts/version.py get version
```

Synchronization updates the five subpackages, MCP's client dependency minimum,
Helm chart/application versions, deployment images and current installation
examples. Historical migrations, compatibility minimums, backend capability
evidence and protocol versions are maintained separately. CI rejects drift.
The root `tool.hugegraph.ci` table also defines the shared uv version and primary
Python runtime; see [CI selection](quality/ci.md) for full-validation controls.
Ruff and ty use `>=` lower bounds in root development dependencies. CI uses
those same ranges, and local pre-commit hooks run Ruff through uv without a fixed
hook revision or a separate tool version.

Build the source LLM image with `bash scripts/build_llm_image.sh`. The script
uses the root image repository and release tag. Set `PYTHON_FOR_RELEASE` to a
Python 3.11+ executable when `python3` is older. Before images are published,
build locally or follow the source installation instructions; release tags in
documentation become pullable only after publication.

`scripts/apache-release.sh [version [username [password]]]` retains its existing
argument order and defaults to the root version. It checks metadata and the
release branch version before archiving/signing/uploading. Follow the existing
ASF release process for signatures, voting and distribution.

Python publication uses the existing external
[`hugegraph/actions` workflow](../hugegraph-mcp/docs/releasing.md): validate with
`publish=false`, publish the client first, then MCP, and verify installation
from outside the checkout. Already uploaded versions must not be overwritten.
