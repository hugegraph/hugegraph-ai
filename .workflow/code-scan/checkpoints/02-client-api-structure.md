# T1 Client API and Structure Checkpoint

Status: completed

## Scope

- `hugegraph-python-client/src/pyhugegraph/api/`
- `hugegraph-python-client/src/pyhugegraph/structure/`
- `hugegraph-python-client/src/tests/api/`

## Findings

- `CS-006`: graph query APIs concatenate query strings without URL encoding.
- `CS-007`: `PropertyKey` builder exposes `calc*()` / `userdata()` but `create()`
  drops them.
- `CS-008`: Gremlin API rewrites all failures as `NotFoundError`.
- `CS-018`: `IndexLabel.by()` loses multi-field order through `set`.
- `CS-019`: `getVertexByCondition()` accepts `page` but drops next-page token.

## Test-quality Notes

- Added `FIXME:` comments in `test_graph.py`, `test_schema.py`, and
  `test_gremlin.py`.
- Recorded false-green and shared-state client tests as `CS-034` and `CS-035`.
