# Flaky Risk Ledger

| Test or area | Risk | Current mitigation | Future action |
|---|---|---|---|
| LLM CI HugeGraph readiness | `sleep 10` can hide slow startup or race with tests | P0 records current issue only | G1 should replace with HugeGraph `1.7.0` service health check |
| LLM external skip control | Global `SKIP_EXTERNAL_SERVICES=true` prevents selected real HugeGraph boundary tests from opting in | P0 records current issue only | G0/G1 should switch to default-only skip semantics and explicit Layer B fixture behavior |
| Client integration selection | Full client suite currently mixes service-bound and local tests | P0 records current issue only | G0/G1 should add markers and fixture-driven selection |
| Open PR collisions | Parallel PRs touch config, vertex IDs, Gremlin examples, flow tests, vector/property embedding, and async API | Quarantine list in `00-preflight.md` | Inspect exact files before goals touching those surfaces |
| Local HugeGraph service for G2 | Docker daemon unavailable and no service reachable at `127.0.0.1:8080` | G2 paused before adding unverifiable service-bound tests | Start Docker/OrbStack and HugeGraph `1.7.0`, then resume G2 |
