# Production Change Ledger

| Goal | File | Change | Test proving it | Reason | Risk |
|---|---|---|---|---|---|
| G2 | `hugegraph-python-client/src/pyhugegraph/utils/util.py` | Preserve backend error envelope details for non-404 HTTP errors and prefer server `message` over `exception`. | `uv run pytest hugegraph-python-client/src/tests/api/test_response_validation.py -q` | Response validation contract gap for 500 backend envelopes. | Low; narrows error wrapping to preserve parsed server details while keeping 404 mapping. |
