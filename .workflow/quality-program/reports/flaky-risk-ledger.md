# Flaky Risk Ledger

| Test or area | Risk | Current mitigation | Future action |
|---|---|---|---|
| LLM CI HugeGraph readiness | `sleep 10` can hide slow startup or race with tests | P0 records current issue only | G1 should replace with HugeGraph `1.7.0` service health check |
| LLM external skip control | Global `SKIP_EXTERNAL_SERVICES=true` prevents selected real HugeGraph boundary tests from opting in | P0 records current issue only | G0/G1 should switch to default-only skip semantics and explicit Layer B fixture behavior |
| Client integration selection | Full client suite currently mixes service-bound and local tests | P0 records current issue only | G0/G1 should add markers and fixture-driven selection |
| Open PR collisions | Parallel PRs touch config, vertex IDs, Gremlin examples, flow tests, vector/property embedding, and async API | Quarantine list in `00-preflight.md` | Inspect exact files before goals touching those surfaces |
| Local HugeGraph service for G2 | Local Docker/OrbStack availability can block selected Layer B tests | G2 resumed after starting `hugegraph/hugegraph:1.7.0`; full client integration suite passed with `HUGEGRAPH_REQUIRED=true` | Keep using explicit readiness checks and fail selected tests when required service is unavailable |
| Legacy mock-only integration tests | `test_kg_construction.py` and `test_graph_rag_pipeline.py` define local replacement pipeline classes | G5 added production-code smoke tests for KG, GraphRAG, and Text2Gremlin as the authoritative smoke gate | Convert or demote legacy mock-only files after quality program scope |
| GraphRAG smoke BLEU warnings | Short deterministic strings trigger NLTK BLEU zero-overlap warnings | Assertions check structured non-empty output, not BLEU score value | Consider smoothing or a deterministic scorer if warnings become noisy in CI |
