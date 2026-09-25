# Publishing HugeGraph MCP

HugeGraph MCP is distributed from PyPI and launched with `uvx`. It depends on
`hugegraph-python`, so release the client before the MCP package.

## Repository Setup

Configure PyPI Trusted Publishers for these GitHub environments and workflows:

| PyPI project | GitHub environment | Workflow |
| --- | --- | --- |
| `hugegraph-python` | `pypi-hugegraph-python-client` | `publish-hugegraph-python-client.yml` |
| `hugegraph-mcp` | `pypi-hugegraph-mcp` | `publish-hugegraph-mcp.yml` |

Require reviewer approval on both GitHub environments. The workflows request
short-lived OIDC credentials and do not use long-lived PyPI API tokens.

## Release Order

1. Merge the client fixes required by MCP.
2. Set a new, unpublished client version and publish it by pushing
   `client-v<version>`.
3. Confirm that the client version is available from PyPI, then update the MCP
   minimum client dependency to that version and verify the published-client contracts.
4. Update and verify the MCP package version, then publish it by pushing
   `mcp-v<version>`, for example `mcp-v1.7.0`.
5. Verify the public installation:

   ```bash
   uvx --from hugegraph-mcp==1.7.0 hugegraph-mcp
   ```

The MCP build job resolves its wheel only against published dependencies, so it
stops before upload when the required client release is unavailable or fails the
client ID and schema contract tests. The tests run outside the checkout to prevent
local source imports from masking an incompatible published wheel.

The distribution name is `hugegraph-python`; Python imports remain `pyhugegraph`
and the source directory remains `hugegraph-python-client/`. The GitHub environment
and workflow identifiers above are deployment configuration, not PyPI package names;
keep them aligned with the configured Trusted Publisher.

Before releasing MCP, also verify the required client behavior (including graphspace
and auth routing) against the published client wheel. Installing successfully alone
does not prove that the published client contains the fixes in this branch.

For local wheel validation with uv, create a clean environment and run:

```bash
uv --no-config pip install --python <isolated-python> <mcp-wheel> <client-wheel>
```

This avoids applying the root LLM workspace constraints to the standalone MCP
distribution. To check published dependencies, omit `<client-wheel>` and use
`--index-url https://pypi.org/simple` without local `--find-links`.

During PR development, the published client is expected to exclude client fixes
that have not yet been merged and released. Package-name migration is verified by
installing the renamed distribution and starting MCP; full branch compatibility is
verified with the client built from the same checkout. The published-client
contract check is a release prerequisite and runs in the tag-triggered publishing
workflow. Follow the release order above once the client fixes are merged.
