# ingest_graph_data Validation Fix Plan

## Background

Current `ingest_graph_data` validation still misses two PRD-required checks:

- Vertex primary keys are not enforced from the live HugeGraph schema.
- Edge `source` / `target` endpoints are not resolved against vertices in the payload.

These gaps can make dry-run return a valid `plan_hash` for data that will fail during import or create incorrect graph relationships.

## Goals

- Use live schema primary key definitions as the source of truth.
- Reject graph data when an edge endpoint cannot be resolved to a vertex in the same payload.
- Keep the existing MCP tool interface unchanged.
- Return existing structured envelope errors, primarily `SCHEMA_MISMATCH`.

## Implementation Plan

### 1. Parse primary keys from live schema

In `hugegraph_mcp/tools/ingest_graph_data.py`, extend live schema parsing to build:

- `schema_primary_keys: dict[str, list[str]]`
- `schema_props: dict[str, set[str]]`
- `schema_property_types: dict[str, str]`

Support both snake_case and camelCase schema fields where applicable:

- `primary_keys`
- `primaryKeys`

For every vertex in `graph_data["vertices"]`:

- Read its `label`.
- Look up primary keys from `schema_primary_keys[label]`.
- Require every primary key to exist in `vertex["properties"]`.
- Require primary key values to be non-empty.
- Return validation errors such as:
  - `vertex 0 missing primary key value for label 'person': name`

Do not rely on payload-provided `vertex["primary_keys"]` as the authority.

### 2. Build a payload vertex identity index

While validating vertices, build an index of vertices that edges can resolve against.

Supported identities:

- Explicit ID:
  - `(label, "id", vertex["id"])`
- Schema primary key tuple:
  - `(label, "pk", (pk1_value, pk2_value, ...))`

If two vertices produce the same identity, report duplicate risk. This can be a warning first unless the import path would definitely fail.

### 3. Resolve edge endpoints

Support both current MCP payload shape and HugeGraph-AI extraction shape.

Current MCP shape:

```json
{
  "label": "knows",
  "source_label": "person",
  "target_label": "person",
  "source": {"name": "Alice"},
  "target": {"name": "Bob"}
}
```

HugeGraph-AI shape:

```json
{
  "label": "knows",
  "outV": "1:Alice",
  "outVLabel": "person",
  "inV": "1:Bob",
  "inVLabel": "person"
}
```

Validation rules:

- `source_label` / `target_label` or `outVLabel` / `inVLabel` must match the EdgeLabel schema.
- `source` must resolve to an existing payload vertex.
- `target` must resolve to an existing payload vertex.
- If endpoint properties are missing required primary keys, return `SCHEMA_MISMATCH`.
- If endpoint identity does not exist in the vertex index, return `SCHEMA_MISMATCH`.

Example errors:

- `edge 0 source endpoint missing primary key for label 'person': name`
- `edge 0 target endpoint not found for label 'person': {'name': 'Bob'}`

### 4. Preserve existing safety gates

Keep the current flow:

- Fetch live schema before validation.
- If live schema cannot be read, return `CONNECTION_FAILED`.
- If validation fails with live schema present, return `SCHEMA_MISMATCH`.
- Dry-run still returns `plan_hash`, `mutation_summary`, and warnings.
- Confirm write still requires non-readonly, `confirm=True`, and matching `plan_hash`.

### 5. Add focused tests

Add tests in `hugegraph-mcp/tests/test_ingest_graph_data.py`:

- Live schema requires `person.name`; vertex missing `name` returns `SCHEMA_MISMATCH`.
- Edge target references `Bob`, but payload only contains `Alice`; returns `SCHEMA_MISMATCH`.
- Edge endpoint object missing required primary key returns `SCHEMA_MISMATCH`.
- Valid payload with `Alice`, `Bob`, and `Alice -> Bob` passes dry-run.
- `outV/outVLabel/inV/inVLabel` payload shape resolves successfully.
- Duplicate vertex identity produces a duplicate warning.

## Verification

Run:

```powershell
cd D:\Code\agent_learning\hugegraph-ai\hugegraph-mcp
uv run pytest tests/test_ingest_graph_data.py
uv run pytest
```

Expected result:

- `test_ingest_graph_data.py` covers primary key and endpoint resolution.
- Full `hugegraph-mcp` regression remains green.

