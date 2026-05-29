# P1-T3.5 审视报告：flows/ 下 flow 文件的请求路径同步 IO

> 见 [tasks.md](./tasks.md) P1-T3.5

## 审视范围

- `flows/rag_flow_raw.py`
- `flows/rag_flow_vector_only.py`
- `flows/rag_flow_graph_only.py`
- `flows/rag_flow_graph_vector.py`
- `flows/text2gremlin.py`
- `flows/common.py`（BaseFlow）

## 审视方法

```bash
grep -nE "requests\.|import requests|from requests" \
  hugegraph-llm/src/hugegraph_llm/flows/
```

并按 file 目视检查 `prepare` / `build_flow` / `post_deal` / `post_deal_stream` 四个钩子。

## 结论

| 文件 | 请求路径同步 IO | 备注 |
|---|---|---|
| `rag_flow_raw.py` | ❌ 无 | 仅 pipeline 搭建 + 读 wkflow_state |
| `rag_flow_vector_only.py` | ❌ 无 | 同上 |
| `rag_flow_graph_only.py` | ❌ 无 | 同上 |
| `rag_flow_graph_vector.py` | ❌ 无 | 同上 |
| `text2gremlin.py` | ❌ 无 | 同上 |
| `common.py` (BaseFlow) | ❌ 无 | 抽象基类 + `post_deal_stream` 透传 |

flow 文件本身 **不调用** `requests.*`，所有 IO 都被封装在 node 实现里：
- `GraphQueryNode` / `GremlinExecuteNode` / `SchemaNode` 走 pyhugegraph（同步 SDK）
- `VectorQueryNode` / `SemanticIdQueryNode` 走本地 faiss + 向量计算
- `MergeRerankNode` 调用 reranker 模型（cohere / siliconflow → `requests`）

这些 **间接同步调用** 在 P1-T3.5 范围之外，由 Phase 2 处理：

- `models/rerankers/cohere.py` / `siliconflow.py` → P2-T3
- `operators/common_op/merge_dedup_rerank.py` → P2-T3
- `utils/hugegraph_utils.py` / `operators/hugegraph_op/schema_manager.py` → P2-T4
- `pyhugegraph` 调用链 → P2-T5（AsyncHugeGraphAdapter）

## 行动结论

- Phase 1 不在 flow 文件层面追加 IO 替换。
- Phase 2 退出标准 §"间接同步调用门禁"涵盖以上所有 wrapper 调用，需在
  `spec/async_streaming_api/blocking_call_audit.md` 中按 file:line 列出并归类。
