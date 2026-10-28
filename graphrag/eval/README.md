# hugegraph-llm-eval

An installable evaluation SDK for GraphRAG pipelines and external Python projects.

It is the measurement layer of the project: retrieval, answer and property-graph
scoring rules live here, while `hugegraph-llm` keeps the pipeline, persistence and
reports. Callers provide inputs, inject a judge model only when a metric needs one,
and receive structured records that can be stored elsewhere or fed back into a
repair loop.

## Install

This package ships with the repository and has not been published to a public
index by this change. Use an editable install or a built wheel:

```bash
# in your own project, with the path replaced by the actual checkout
uv add --editable /absolute/path/hugegraph-ai/graphrag/eval

# or build a wheel and install it
uv build --no-sources /absolute/path/hugegraph-ai/graphrag/eval --out-dir /tmp/llm-eval-dist
uv add /tmp/llm-eval-dist/hugegraph_llm_eval-1.8.0-py3-none-any.whl
```

Optional extras add vendor-specific metrics and transports:

| Extra | Adds |
| --- | --- |
| `graph` | semantic entity and triple matching (`networkx`) |
| `rouge` | ROUGE-L answer scoring (`rouge-score`, `jieba`) |
| `openai` | OpenAI-compatible judge transport (`openai`) |

The base install depends on Pydantic only. Python 3.12–3.14 are supported.

## Quick start

No judge model is needed for ranking metrics:

```python
from hugegraph_llm_eval import (
    EvaluationContext,
    EvaluationOptions,
    InMemoryArtifactStore,
    MRREvaluator,
    RecallAtKEvaluator,
    retrieval_input,
)
from hugegraph_llm_eval.contracts.identity import EvaluationRunId
from hugegraph_llm_eval.integrations.retrieval.materializers import RetrievalArtifactMaterializer
from hugegraph_llm_eval.utils.clock import utc_now

store = InMemoryArtifactStore()
evaluation_input = retrieval_input(
    store,
    candidate_doc_ids=["doc-b", "doc-a"],
    reference_doc_ids=["doc-a"],
    question="Which service rotates its tokens?",
)
options = EvaluationOptions(request_key="case-1")
context = EvaluationContext(
    run_id=EvaluationRunId.new(),
    request_key=options.request_key,
    deadline=options.deadline,
    cancellation=options.cancellation,
)
materializer = RetrievalArtifactMaterializer(store)

for evaluator in (
    RecallAtKEvaluator(materializer, k_values=(1, 3), clock=utc_now),
    MRREvaluator(materializer, clock=utc_now),
):
    record = evaluator.evaluate(evaluation_input, context)
    print(record.invocation_key, [(m.name, m.value) for m in record.measurements])
```

## Run every metric

[`examples/all_metrics.py`](examples/all_metrics.py) exercises all sixteen metrics and both
entry points in one run. It uses a deterministic stand-in judge unless a model is
configured, so it runs without an API key:

```bash
uv add --editable /absolute/path/hugegraph-ai/graphrag/eval --extra graph --extra rouge
python examples/all_metrics.py

# same script against a real model
EVAL_JUDGE_MODEL=<model> EVAL_JUDGE_API_KEY=<key> python examples/all_metrics.py
```

| Group | Metrics |
| --- | --- |
| Retrieval | `recall@k`, `hit@k`, `MRR`, context precision, context relevancy, context entity recall, evidence recall |
| Answers | ROUGE-L, answer correctness, factual correctness, faithfulness, noise sensitivity |
| Graphs | schema validity, graph faithfulness, semantic entity matching, semantic triple matching |

## Batch API

Run several metrics with ordering, bounded concurrency, retries, deadline and
cancellation applied by the engine:

```python
from hugegraph_llm_eval import EvaluationOptions, evaluate

result = evaluate(
    [recall, mrr, semantic_entity],
    evaluation_input,
    options=EvaluationOptions(request_key="case-1", max_concurrency=4, max_attempts=2),
)
print(result.status, [record.status for record in result.records])
```

`status` is `completed`, `partial`, `failed` or `cancelled`; record-level failures
stay in the result instead of raising.

Two knobs bound the work, and both have a hard upper bound of 8:

| Option | Bounds |
| --- | --- |
| `max_concurrency` | evaluators running inside one input |
| `max_samples` | inputs running at once in `evaluate_many` |

Every sample and metric of one call shares a single provider limit of
`max_samples × max_concurrency` concurrent judge calls, and a single
`budget_usd`. Nested work — such as the candidate batches of a semantic
matcher — waits on that same limit instead of multiplying it:

```python
results = evaluate_many(
    [recall, mrr, semantic_entity],
    inputs,
    options=EvaluationOptions(request_key="batch", max_samples=4, max_concurrency=4),
)
```

## Judge-based metrics with a real model

Any OpenAI-compatible endpoint works. `openai_judge` builds the transport, and
`max_attempts` bounds provider calls per metric:

```python
from hugegraph_llm_eval import (
    GraphFaithfulnessEvaluator,
    JudgeContent,
    evaluate,
    graph_judge_prompt,
    graph_judge_rubric,
    graph_review_input,
    openai_judge,
)
from hugegraph_llm_eval.integrations.graph_extraction.materializers import GraphArtifactMaterializer

judge = openai_judge(model="your-model", api_key="...", base_url="https://your-gateway/v1")
evaluation_input = graph_review_input(store, candidate=candidate, source_text=source, schema=schema)
materializer = GraphArtifactMaterializer(store)
evaluator = GraphFaithfulnessEvaluator(
    materializer,
    judge=judge,
    prompt=JudgeContent(component=prompt_ref, text=graph_judge_prompt("faithfulness", "en")),
    rubric=JudgeContent(component=rubric_ref, text=graph_judge_rubric("faithfulness", "en")),
    clock=utc_now,
)
result = evaluate([evaluator], evaluation_input, options=EvaluationOptions(request_key="case-1"))
```

A complete runnable version is in [`examples/real_model.py`](examples/real_model.py):

```bash
export EVAL_JUDGE_MODEL=<model>
export EVAL_JUDGE_API_KEY=<key>
# export EVAL_JUDGE_BASE_URL=<gateway>   # optional
# export EVAL_JUDGE_PROVIDER=<provider>  # optional, labels the judge descriptor
python examples/real_model.py
```

It scores a small property graph against its source text and prints the
measurements plus each unsupported item. Without configuration it explains what
to set and exits with code 2.

## Input builders

| Helper | Input schema | Metrics |
| --- | --- | --- |
| `answer_input` | answer / references / question + contexts | ROUGE-L, answer correctness, factual correctness, faithfulness, noise sensitivity |
| `retrieval_input` | candidate and reference doc ids, question | recall@k, hit@k, MRR, context precision/relevancy, entity and evidence recall |
| `graph_review_input` | candidate graph + source text + schema | schema validity, graph faithfulness |
| `graph_comparison_input` | candidate + reference graph + schema | semantic entity / triple matching |
| `graph_extraction_input` | candidate + reference + source + schema | offline extraction metrics |

## Design boundary

| In this package | Stays in the calling application |
| --- | --- |
| Domain contracts and ports | Databases, artifact stores and file layout |
| Evaluators and judge protocol | Vendor SDK configuration and credentials |
| Concurrency, retry and cancellation semantics | CLI, web UI and report rendering |
| Structured findings usable as repair input | Product-specific pipeline adapters |

The core must not import application configuration, UI, graph clients or logging
initialization. Vendor dependencies are imported only when the corresponding
extra is installed.
