# CI selection and validation

The **HugeGraph AI CI** workflow owns push/PR selection and shared configuration.
Its preflight checks synchronized release metadata and runs the release-tooling
and selection-policy tests. The selected suites and changed paths are recorded
in the job summary. A failed diff or preflight fails CI rather than skipping tests.

| Change | Default runtime tests |
| --- | --- |
| README, Markdown or documentation | No runtime environment, Docker or CodeQL |
| Python client | Client plus downstream LLM and MCP |
| LLM | LLM |
| MCP | MCP |
| Root dependency/release configuration or shared CI setup | Client, LLM and MCP |
| Module CI workflow | That module and its downstream consumers |
| Docker configuration or LLM image build script | LLM |

Ruff runs once for Python/lint/shared configuration changes using `uvx`, without
installing application dependencies. License checks share the preflight runner.
Dependency review runs for dependency changes on same-repository PRs; its token
restrictions for fork PRs are unchanged. Deleted files and both sides of a rename
participate in selection.

Ordinary runs use the primary Python version defined in `tool.hugegraph.ci` in
the root `pyproject.toml`. Each module reuses one dependency environment and one
HugeGraph service for its unit, integration and smoke phases. Existing coverage
thresholds remain enforced. Integration tests fail if the service is unavailable.
Server image digests and the `/versions` response are logged; `versions.core`
must match the prepared release version. Backend capability gates remain unchanged.

`astral-sh/setup-uv` caches downloads and Python installations by component,
Python runtime and relevant manifests. LLM jobs also cache NLTK and tiktoken data.
Ruff, dependency review and CodeQL each have a single job rather than a runtime
matrix. PR updates and new main pushes cancel superseded runs.

The default toolchain is **uv + Ruff + ty**. The uv version is defined in
`tool.hugegraph.ci`; Ruff and ty use `>=` lower bounds in root development dependencies.
CI reads those lower bounds and uses the same ranges. Local pre-commit hooks run
Ruff through uv, without a fixed remote hook revision. The legacy formatting/lint script now uses uv/Ruff/ty
instead of Black/Pylint; `-b` and `-p` retain their format/lint selections.

ty runs on the primary-runtime client, LLM and MCP jobs by default, without
adding runners. MCP uses its standalone Python environment for import resolution.
Application type checks retain the existing advisory status: the current ty
baseline contains unresolved diagnostics, so a ty failure is visible but does
not fail `CI Result`. Ruff and tests remain blocking. Clearing that baseline and
making application type checks blocking is separate work.
Release/CI scripts have a clean ty baseline and are checked as a blocking step
in the existing quality runner, using their Python 3.11+ target.

## Full and optional checks

- Weekly on ASF main (Monday 06:00 Asia/Taipei), release-branch pushes, and manual
  **full** runs validate client/LLM on Python 3.10 and 3.11, MCP on 3.10–3.12,
  plus CodeQL. Docker integration runs
  once per module on the primary Python runtime.
- Use **Run workflow → mainline** for the primary-runtime checks on the selected
  branch, **full** for the complete matrix, **codeql** for security scanning, or
  **dependencies** with a base ref for dependency review.
- **Rerun CI** is manual and accepts a failed run ID. Automatic delayed retries
  were removed; a deterministic test failure no longer allocates retry runners.

When CodeQL is selected, preflight reads the repository's workflow metadata with
`actions:read`. An active `dynamic/github-code-scanning/codeql` workflow means
GitHub default setup already owns scanning, so the custom CodeQL job is skipped.
This avoids both duplicate runners and GitHub's rejection of advanced SARIF
uploads while default setup is enabled. Without an active default scanner, the
selected custom workflow runs normally. Metadata-query failures fail preflight.
GitHub default scans keep their own triggers and check results, outside
`CI Result`; a manual `codeql` selection does not force a new default-setup scan.

## Required check migration

Use **CI Result** as the required branch-protection check. It fails for any
failed/cancelled selected job or failed preflight and accepts intentionally
skipped suites. Replace old per-module matrix check names in repository rules
when adopting this workflow; code changes here do not update GitHub rules.

The regular test workflows are reusable and receive configuration from preflight.
They do not independently trigger duplicate runs. PR labeling and other repository
administration workflows retain their existing triggers.
