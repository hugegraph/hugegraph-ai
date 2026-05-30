# G2 Client Contract Checkpoint

## Status

Blocked before client contract edits.

## Blocker

Required HugeGraph service is unavailable locally:

- `docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'` failed because the Docker daemon is not reachable at `/Users/imbajin/.orbstack/run/docker.sock`.
- Direct `GET http://127.0.0.1:8080/versions` failed with `ConnectionRefusedError`.

The plan requires Layer B client contract tests to run against a real HugeGraph service and forbids silently skipping selected HugeGraph integration tests. Continuing into G2 test additions without a service would leave the core contract proof unverifiable.

## Commands Run

```bash
docker ps --format '{{.Names}} {{.Image}} {{.Ports}}'
uv run python -c "import requests; print(requests.get('http://127.0.0.1:8080/versions', timeout=5).text[:200])"
```

## Files Touched

- `.workflow/quality-program/checkpoints/03-client-contract.md`
- `.workflow/quality-program/quality-state.json`
- `.workflow/quality-program/reports/flaky-risk-ledger.md`

## Production Changes

None.

## Tests Added or Changed

None.

## Failure Classification

Service setup failure: HugeGraph Server `1.7.0` is not reachable, and Docker cannot start or inspect containers because the local daemon is unavailable.

## Resume Condition

Start a HugeGraph `1.7.0` service reachable at `http://127.0.0.1:8080`, or start the local Docker/OrbStack daemon so the service can be launched with:

```bash
docker run -d --name hugegraph-quality -p 8080:8080 -e PASSWORD=admin hugegraph/hugegraph:1.7.0
```

Then resume G2 from Step G2.1.
