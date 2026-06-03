# Final Code Scan Report

Date: 2026-05-31
Scope: `hugegraph-llm`, `hugegraph-python-client`

## Summary

The scan completed all planned lanes. The highest-risk result is one P0 security issue in the `hugegraph-llm` admin log API. The broader pattern is that core boundary failures are often hidden: client transport errors are retyped, provider failures are returned as normal text, graph/vector dependency failures can be converted to empty results, and several integration tests use local stand-ins rather than production flows.

During the scan phase, no behavior-changing source fixes were made. Only scan documents and `FIXME:` comments were added. Follow-up fixes are listed later in this report.

## Scope Covered

- `hugegraph-python-client/src/pyhugegraph/`
- `hugegraph-python-client/src/tests/`
- `hugegraph-llm/src/hugegraph_llm/`
- `hugegraph-llm/src/tests/`
- Cross-module usage of `pyhugegraph` from `hugegraph-llm`

## Issue Distribution by Priority

| Priority | Count | Theme |
|---|---:|---|
| P0 | 1 | Admin log path traversal / weak default admin controls |
| P1 | 16 | Incorrect error contracts, config/global-state corruption, graph import correctness, provider factory failures |
| P2 | 9 | Contract drift, prompt/config side effects, vector backend semantics, backup correctness |
| P3 | 3 | Resource lifecycle and performance/cost risks |
| P4 | 8 | Ineffective tests, fake integration coverage, weak assertions, skipped/print-only tests |
| P5 | 0 | No minor style-only issues recorded |

## Top P0-P2 Findings

1. `CS-001`: `/logs` can read arbitrary files through path traversal.
2. `CS-002`: Client request/error logs can leak auth secrets.
3. `CS-004`: `ResponseValidation` can turn a broken `2xx` payload into `{}`.
4. `CS-008`: Gremlin failures are all rewritten as `NotFoundError`.
5. `CS-011`: Per-request `client_config` overwrites process-global graph settings.
6. `CS-013`: KG extraction stringifies values that the importer rejects, then can report success.
7. `CS-014`: Graph/vector dependency failures are treated as empty retrieval.
8. `CS-015`: LiteLLM embedding factory crashes for an advertised config branch.
9. `CS-020`: Runtime YAML prompts and prompt contract tests have drifted.
10. `CS-023`: Vector recall parameters are lost between flow/node/operator boundaries.

## Test-quality and FIXME Summary

The required `FIXME:` markers were added near the affected test or boundary code. Key clusters:

- API contract gaps: `/logs`, `/rag`, `/rag/graph`, `/config/*`.
- Client contract gaps: auth routing, URL encoding, Gremlin error semantics, schema builder payloads.
- Flow/import gaps: `PropertyGraphExtract -> Commit2Graph`, graph/vector dependency failure propagation.
- Provider/backend gaps: OpenAI error propagation, LiteLLM construction/streaming, vector backend threshold semantics.
- Fake integration gaps: GraphRAG/RAG/KG tests that define local replacement classes.

See `reports/test-quality-ledger.md` for the full list.

## Cross-module Contract Risks

`hugegraph-llm` assumes `pyhugegraph` failures are meaningful and typed, but the client currently collapses several of them:

- Gremlin errors become `NotFoundError`.
- Response parse failures can become `{}`.
- URL-prefix routing can target the wrong path.
- Graphspace support can be disabled by a transient constructor-time probe.

Those client behaviors directly affect `hugegraph-llm` graph import, GraphRAG, Text2Gremlin execution, and backup utilities.

## Style-only Fixes Applied

None.

## Verification Commands

- `git diff --check`: passed.
- `uv run ruff check <edited-python-files>`: passed for all Python files touched by `FIXME:` comments.
- `git status --short`: reviewed before final staging; unrelated `.workflow/pr68-review/` remains untracked and was left untouched.

## Recommended Next Fix Plan

1. Fix `CS-001` immediately: lock down `/logs` path handling and default admin credentials. Status: fixed after the scan.
2. Fix the client error-contract cluster: `CS-002`, `CS-004`, `CS-008`. Status: fixed after the scan.
3. Fix graph import correctness: `CS-013`, then add the missing round-trip tests. Status: fixed after the scan.
4. Fix global config mutation and provider validation: `CS-011`, `CS-012`. Status: fixed after the scan.
5. Replace fake integration tests with production-flow smoke coverage before broader refactors. Status: fixed after the scan.

## Fix Progress After Scan

- `CS-001`: fixed by rejecting insecure default admin tokens and validating log file names before `log_stream()` receives a path. Verified with `SKIP_EXTERNAL_SERVICES=true uv run pytest hugegraph-llm/src/tests/api/test_admin_api.py -q`.
- `CS-002`: fixed by redacting sensitive request fields before client debug/error logs are emitted.
- `CS-004`: fixed by raising `ResponseParseError` for malformed successful responses.
- `CS-008`: fixed by preserving lower-level exceptions from Gremlin execution instead of wrapping every failure as `NotFoundError`.
- `CS-013`: fixed by preserving extracted property value types through the full extraction-to-commit path.
- `CS-011`: fixed by updating global graph settings only for explicitly supplied `client_config` fields.
- `CS-012`: fixed by rejecting unsupported provider types at request validation before global settings are mutated.
- `CS-030`: fixed by replacing local fake integration flows with production Flow/Operator smoke tests.
