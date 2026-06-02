# T1 Client Transport Checkpoint

Status: completed

## Scope

- `hugegraph-python-client/src/pyhugegraph/client.py`
- `hugegraph-python-client/src/pyhugegraph/utils/`
- `hugegraph-python-client/src/pyhugegraph/api/auth.py`
- `hugegraph-python-client/src/pyhugegraph/api/common.py`

## Findings

- `CS-002`: request/error logging can leak auth secrets.
- `CS-003`: leading-slash routes drop configured URL path prefixes.
- `CS-004`: successful response parse failures are swallowed as `{}`.
- `CS-005`: graphspace support depends on one fragile constructor-time probe.
- `CS-027`: each lazy manager owns an independent session with no unified close.

## Test-quality Notes

- Added `FIXME:` in `test_auth_routing.py` because the dummy session mirrors
  production resolver behavior instead of exercising `HGraphSession.resolve()`.
