# Code Scan Ledger

This directory tracks the 2026-05-31 code logic/design scan for:

- `hugegraph-llm`
- `hugegraph-python-client`

It is separate from `.workflow/quality-program/` because this scan records issues first and does not implement behavior-changing fixes.

## Rules

- Record logic/design/performance issues in `reports/issues.md`.
- Add `FIXME:` comments only for missing or ineffective tests around core behavior.
- Keep checkpoint files current after each scan lane.
- Commit after setup and after each coherent large sub-slice.

## Primary References

- `docs/specs/2026-05-31-hugegraph-ai-code-scan-design.md`
- `docs/plans/2026-05-31-hugegraph-ai-code-scan.md`
