# Module Scan Map

## hugegraph-python-client

| Layer | Paths | Status | Notes |
|---|---|---|---|
| Transport/auth/routing | `src/pyhugegraph/client.py`, `src/pyhugegraph/utils/`, `src/pyhugegraph/api/auth.py`, `src/pyhugegraph/api/common.py` | completed | L1 |
| API and structure | `src/pyhugegraph/api/`, `src/pyhugegraph/structure/` | completed | L2 |
| Tests | `src/tests/` | completed | L6 |

## hugegraph-llm

| Layer | Paths | Status | Notes |
|---|---|---|---|
| API/config/prompt | `src/hugegraph_llm/api/`, `src/hugegraph_llm/config/`, `src/hugegraph_llm/resources/` | completed | L3 |
| Flows/nodes/operators | `src/hugegraph_llm/flows/`, `src/hugegraph_llm/nodes/`, `src/hugegraph_llm/operators/`, `src/hugegraph_llm/state/` | completed | L4 |
| Indices/models/utils | `src/hugegraph_llm/indices/`, `src/hugegraph_llm/models/`, `src/hugegraph_llm/utils/` | completed | L5 |
| Tests | `src/tests/` | completed | L6 |

## Cross-module

| Boundary | Status | Notes |
|---|---|---|
| `hugegraph-llm` callers of `pyhugegraph` | completed | L7 |
