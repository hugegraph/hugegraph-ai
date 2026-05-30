# HugeGraph AI Quality Program

This directory tracks the restartable execution state for the HugeGraph AI
Quality Program v2.

## Source of Truth

- `docs/superpowers/specs/2026-05-31-hugegraph-ai-quality-program-design.md`
- `docs/superpowers/plans/2026-05-31-hugegraph-ai-quality-program.md`
- `AGENTS.md`
- `hugegraph-llm/AGENTS.md`
- `rules/README.md`

## Goal Order

```text
P0 -> G0 -> G1 -> G2 -> G3 -> G4 -> G5 -> G6 -> G7
```

## Resume Instructions

1. Read `quality-state.json`.
2. Open the checkpoint matching `current_goal`.
3. Continue from the first unchecked step in the implementation plan.
4. Update `quality-state.json` and the matching checkpoint after every goal.

## Hard Constraints

- Do not silently skip selected HugeGraph integration tests.
- Use `hugegraph/hugegraph:1.7.0` for Layer B unless an exception is documented.
- Do not require real LLM, embedding, reranker, vector DB, or UI credentials outside Layer D.
- Do not perform deferred broad refactors as part of this campaign.
- Every production-code change must have a proving test and production-change-ledger entry.
