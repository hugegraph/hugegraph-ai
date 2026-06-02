# T3 Test-quality Checkpoint

Status: completed

## Scope

- `hugegraph-llm/src/tests/`
- `hugegraph-python-client/src/tests/`

## FIXME Candidates

Applied required `FIXME:` comments to 17 affected files. See
`reports/test-quality-ledger.md`.

## Ineffective Test Patterns

- Fake integration tests define local replacements for production flows.
- Core graph import tests patch away branchy behavior.
- Client error tests assert only inside `except` blocks.
- Some integration tests share dirty graph state.
- External/provider smoke tests print without assertions.
- Selected HugeGraph tests can still runtime-skip from shared fixtures.
