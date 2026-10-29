# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

# Prompt text stays on one line so the rendered instruction remains auditable.
# ruff: noqa: E501

"""Stable prompt selection and semantic-judge protocol adaptation."""

from typing import Final, cast

from pydantic import JsonValue

from hugegraph_llm_eval.contracts.digests import canonical_digest
from hugegraph_llm_eval.prompt_templates.answer import (
    _CORRECTNESS_CLASSIFY_PROMPT_ZH,
    _NLI_STATEMENT_PROMPT_ZH,
    _STATEMENT_DECOMPOSE_PROMPT_ZH,
    CORRECTNESS_CLASSIFY_PROMPT,
    NLI_STATEMENT_PROMPT,
    STATEMENT_DECOMPOSE_PROMPT,
)
from hugegraph_llm_eval.prompt_templates.context import (
    _CLAIM_DECOMPOSE_PROMPT_ZH,
    _CONTEXT_PRECISION_PROMPT_ZH,
    _CONTEXT_RELEVANCE_PROMPT_ZH,
    _ENTITY_EXTRACT_PROMPT_ZH,
    _EVIDENCE_RECALL_PROMPT_ZH,
    CLAIM_DECOMPOSE_PROMPT,
    CONTEXT_PRECISION_PROMPT,
    CONTEXT_RELEVANCE_PROMPT,
    ENTITY_EXTRACT_PROMPT,
    EVIDENCE_RECALL_PROMPT,
)
from hugegraph_llm_eval.prompt_templates.graph import (
    _ANSWER_RELEVANCE_PROMPT_ZH,
    _ENTITY_SEMANTIC_MATCH_PROMPT_ZH,
    _EXTRACTION_FAITHFULNESS_PROMPT_ZH,
    _TRIPLE_SEMANTIC_MATCH_PROMPT_ZH,
    ANSWER_RELEVANCE_PROMPT,
    ENTITY_SEMANTIC_MATCH_PROMPT,
    EXTRACTION_FAITHFULNESS_PROMPT,
    TRIPLE_SEMANTIC_MATCH_PROMPT,
)

_PROMPT_REGISTRY: Final[dict[str, dict[str, str]]] = {
    "STATEMENT_DECOMPOSE_PROMPT": {"en": STATEMENT_DECOMPOSE_PROMPT, "zh": _STATEMENT_DECOMPOSE_PROMPT_ZH},
    "NLI_STATEMENT_PROMPT": {"en": NLI_STATEMENT_PROMPT, "zh": _NLI_STATEMENT_PROMPT_ZH},
    "CORRECTNESS_CLASSIFY_PROMPT": {"en": CORRECTNESS_CLASSIFY_PROMPT, "zh": _CORRECTNESS_CLASSIFY_PROMPT_ZH},
    "CONTEXT_PRECISION_PROMPT": {"en": CONTEXT_PRECISION_PROMPT, "zh": _CONTEXT_PRECISION_PROMPT_ZH},
    "CONTEXT_RELEVANCE_PROMPT": {"en": CONTEXT_RELEVANCE_PROMPT, "zh": _CONTEXT_RELEVANCE_PROMPT_ZH},
    "ENTITY_EXTRACT_PROMPT": {"en": ENTITY_EXTRACT_PROMPT, "zh": _ENTITY_EXTRACT_PROMPT_ZH},
    "EVIDENCE_RECALL_PROMPT": {"en": EVIDENCE_RECALL_PROMPT, "zh": _EVIDENCE_RECALL_PROMPT_ZH},
    "CLAIM_DECOMPOSE_PROMPT": {"en": CLAIM_DECOMPOSE_PROMPT, "zh": _CLAIM_DECOMPOSE_PROMPT_ZH},
    "ENTITY_SEMANTIC_MATCH_PROMPT": {
        "en": ENTITY_SEMANTIC_MATCH_PROMPT,
        "zh": _ENTITY_SEMANTIC_MATCH_PROMPT_ZH,
    },
    "TRIPLE_SEMANTIC_MATCH_PROMPT": {
        "en": TRIPLE_SEMANTIC_MATCH_PROMPT,
        "zh": _TRIPLE_SEMANTIC_MATCH_PROMPT_ZH,
    },
    "EXTRACTION_FAITHFULNESS_PROMPT": {
        "en": EXTRACTION_FAITHFULNESS_PROMPT,
        "zh": _EXTRACTION_FAITHFULNESS_PROMPT_ZH,
    },
    "ANSWER_RELEVANCE_PROMPT": {"en": ANSWER_RELEVANCE_PROMPT, "zh": _ANSWER_RELEVANCE_PROMPT_ZH},
}


def get_prompt(name: str, language: str = "zh") -> str:
    """Return the requested historical prompt, defaulting to Chinese."""
    variants = _PROMPT_REGISTRY.get(name)
    if variants is None:
        raise KeyError(f"Unknown LLM-Judge prompt: {name}")
    return variants.get(language, variants["en"])


def answer_judge_prompt(kind: str, language: str = "zh") -> str:
    """Adapt the historical answer-evaluation prompt to the current typed protocol."""
    prompt_name = {
        "decompose": "STATEMENT_DECOMPOSE_PROMPT",
        "verify": "NLI_STATEMENT_PROMPT",
        "correctness": "CORRECTNESS_CLASSIFY_PROMPT",
    }.get(kind)
    if prompt_name is None:
        raise ValueError(f"Unsupported answer judge prompt kind: {kind}")
    historical = get_prompt(prompt_name, language)
    protocol = {
        "decompose": """\
当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 question 和 text 是待拆分内容。
只返回 {\"claims\": [\"原子主张 1\", \"原子主张 2\"]}，不得返回 statements 或其他键。""",
        "verify": """\
当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中包含 context，以及带零基
statement_index 的 statements。必须为每个 statement_index 恰好返回一项 verdict：
{\"verdicts\": [{\"statement_index\": 0, \"entailed\": true, \"reason\": \"上下文支持该主张。\"}]}。
不得返回 statement 或 Yes/No verdict 字段，也不得遗漏任一索引。""",
        "correctness": """\
当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 candidate 与 reference 都带零基
statement_index。返回 {\"matches\": [{\"candidate_index\": 0, \"reference_index\": 1, \"reason\": \"语义等价。\"}],
\"false_positives\": [{\"statement_index\": 2, \"reason\": \"标准答案不支持。\"}],
\"false_negatives\": [{\"statement_index\": 3, \"reason\": \"候选答案遗漏。\"}]}。
每个 candidate index 必须恰好出现在 matches 或 false_positives，每个 reference index 必须恰好出现在
matches 或 false_negatives；不得返回 tp、fp、fn 或其他键。""",
    }[kind]
    return f"{historical}\n\n---\n\n{protocol}"


def answer_judge_prompt_digest(language: str = "zh") -> str:
    """Digest the built-in answer prompts so prompt edits change evaluator identity."""
    texts = {kind: answer_judge_prompt(kind, language) for kind in ("decompose", "verify", "correctness")}
    return canonical_digest(cast(JsonValue, texts)).value


def retrieval_judge_prompt(kind: str, language: str = "zh") -> str:
    """Adapt Chinese retrieval few-shot prompts to the current batched verdict protocols."""
    prompt_name = {
        "context_precision": "CONTEXT_PRECISION_PROMPT",
        "context_relevancy": "CONTEXT_RELEVANCE_PROMPT",
        "evidence_recall": "EVIDENCE_RECALL_PROMPT",
    }.get(kind)
    if prompt_name is None:
        raise ValueError(f"Unsupported retrieval judge prompt kind: {kind}")
    historical = get_prompt(prompt_name, language)
    protocol = {
        "context_precision": (
            "当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 contexts 带零基 context_index。"
            "必须为每个 context_index 恰好返回一项 verdict："
            '{"verdicts":[{"context_index":0,"relevant":true,"reason":"该段能支持回答问题。"}]}。'
            "不得返回单个 verdict、Yes/No 字段或其他键。"
        ),
        "context_relevancy": (
            "当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 contexts 带零基 context_index。"
            "必须为每个 context_index 恰好返回一项 verdict："
            '{"verdicts":[{"context_index":0,"score":2,"reason":"该段完整回答问题。"}]}。'
            "score 只能为 0、1 或 2；不得返回单个 score 或其他键。"
        ),
        "evidence_recall": (
            "当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 evidence 带零基 evidence_index。"
            "必须为每个 evidence_index 恰好返回一项 verdict："
            '{"verdicts":[{"evidence_index":0,"attributed":true,"reason":"上下文直接支持该证据。"}]}。'
            "attributed 必须是布尔值；不得返回 classifications、statement 或其他键。"
        ),
    }[kind]
    return f"{historical}\n\n---\n\n{protocol}"


def graph_judge_prompt(kind: str, language: str = "zh") -> str:
    """Adapt Chinese graph-evaluation few-shot prompts to the current typed protocol."""
    if kind != "faithfulness":
        raise ValueError(f"Unsupported graph judge prompt kind: {kind}")
    historical = get_prompt("EXTRACTION_FAITHFULNESS_PROMPT", language)
    protocol = (
        "当前运行时协议覆盖上面的历史输出格式：下一条 JSON 中的 source_text 是证据，items 中的顶点和边"
        "各自使用 item_index 计数。只返回以下紧凑分区："
        '{"supported_vertex_indices":[0],"supported_edge_indices":[1],'
        '"unsupported_vertex_groups":[{"item_indices":[2],"error_categories":["unsupported_claim"],'
        '"support_reason":null,"error_reason":"原文未支持。","evidence_quote":null}],'
        '"unsupported_edge_groups":[{"item_indices":[3],"error_categories":["condition_loss"],'
        '"support_reason":"关系类型和端点有文本依据。","error_reason":"关系缺少适用条件。",'
        '"evidence_quote":null}]}。'
        "每个顶点和边索引必须恰好出现一次；不得返回 verdicts、idx、Yes/No 或其他键。"
        "不忠实项必须返回一个或多个 error_categories，只能使用：unsupported_claim、numeric_mismatch、"
        "unit_mismatch、condition_loss、range_loss、temporal_mismatch、polarity_reversal、"
        "subject_scope_error。source_text 完全不支持该断言时使用 unsupported_claim；同一项可以同时返回多个类别。"
        "每个不忠实项都必须同时返回 support_reason 和 error_reason；support_reason 只写被原文支持的部分，"
        "没有支持部分时返回 null；error_reason 只写不支持、矛盾或错误的部分。不得把两类内容混写在同一字段。"
        "忠实项不返回 error_categories 或 error_reason。"
    )
    return f"{historical}\n\n---\n\n{protocol}"


_GRAPH_JUDGE_RUBRICS: Final[dict[str, dict[str, str]]] = {
    "faithfulness": {
        "zh": (
            "把每个候选顶点或边视为一个完整事实断言。只有 source_text 明确陈述，或无需引入外部知识即可直接推出该完整断言时，"
            "才能判定为忠实；名称、关系方向、端点或属性任一关键部分缺少依据时，整项判定为不忠实。"
            "不得依赖外部知识。source_snippet 只是定位提示，不是独立证据，必须以 source_text 为准验证。对不支持的项说明缺失的断言，"
            "并从协议规定的 error_categories 中选择一个或多个错误类别；若包含数值、单位、条件、范围、时间、否定或适用对象错误，"
            "必须优先标记对应的具体类别，不要只返回 unsupported_claim。"
            "support_reason 只说明断言中被支持的部分，error_reason 只说明错误或缺失的部分，不要混写。"
        ),
        "en": (
            "Treat each candidate vertex or edge as one complete factual claim. Mark it faithful only when source_text explicitly states "
            "the complete claim or unambiguously entails it without external knowledge. If the entity name, relation direction, "
            "endpoint, or property lacks support, mark the whole item unsupported. Do not rely on external knowledge. "
            "source_snippet is only a locator, not evidence; validate against source_text, explain unsupported claims, and return one or more "
            "controlled error categories for every unsupported item. Separate supported and unsupported portions into support_reason and error_reason."
        ),
    }
}


def graph_judge_rubric(kind: str, language: str = "zh") -> str:
    """Return the centralized rubric for a graph judge."""
    rubrics = _GRAPH_JUDGE_RUBRICS.get(kind)
    if rubrics is None:
        raise ValueError(f"Unsupported graph judge rubric kind: {kind}")
    return rubrics.get(language, rubrics["en"])


def semantic_verdict_prompt(kind: str, language: str = "zh") -> str:
    """Propose semantic pairs without discarding alternatives before assignment."""
    if kind not in {"entity", "triple"}:
        raise ValueError(f"Unsupported semantic graph item kind: {kind}")
    if language == "zh":
        rules = {
            "entity": (
                "实体名称的语义等价是命中条件。label 不一致仍可命中，记录 label_mismatch；"
                "不得仅因 label 不一致返回 candidate_index=null。properties 只作辅助证据，"
                "属性差异记录 property_mismatch，不影响实体匹配。名称含义不对应则不得命中。"
                "例如 Component/auth service 与 Service/authentication service 可以命中并记录"
                " label_mismatch；不能仅因同为 Service 就把 auth service 和 log service 判为等价。"
            ),
            "triple": (
                "关系边是有方向的事实。关系类型只是名称表达，同义词、别名或缩写可命中并记录"
                " relation_mismatch。起点 out_v 和终点 in_v 必须分别语义对应，反向边不得命中。"
                "out_v_label 和 in_v_label 不同仅记录 endpoint_label_mismatch，不能否决名称对应的端点。"
                "properties 只作辅助证据，属性差异记录 property_mismatch。"
                "例如 A DEPENDS_ON B 与 A REQUIRES B 可以命中；B REQUIRES A 不能与前者匹配。"
            ),
        }[kind]
        protocol = (
            "candidates 是当前候选窗口，references 是完整文档标准答案。对每个 reference_index，"
            "返回当前窗口中所有语义等价候选的独立 pair，不要只选最高分候选，也不要在窗口内做一对一分配。"
            "同一个 reference_index 可以对应多个 candidate_index，同一个 candidate_index 也可以对应多个"
            " reference_index；由后处理对所有窗口返回的 pair 统一做最大总权重的一对一匹配。"
            "每个 (reference_index, candidate_index) 只能出现一次；仅当该 reference 在当前窗口完全没有"
            "语义等价候选时，返回一条 candidate_index=null 的记录，不得与该 reference 的命中 pair 混用。"
            "每个 reference 都必须被覆盖，不能输出未提供的 reference 或当前窗口以外的 candidate。"
            "命中时给出 0 到 100 的 match_score；未命中时 match_score=null 并包含 no_semantic_match。"
            "reason 必须说明对应名称、关系、方向或属性的具体依据，不能只写语义等价，不得编造输入证据。"
        )
        output_rule = "只返回下面形式的 JSON；示例展示多个备选 pair，索引仅用于说明结构："
    else:
        rules = {
            "entity": (
                "Match semantically equivalent entity names. A label difference is a soft label_mismatch; "
                "never reject equivalent names solely because their labels differ. Properties are supporting "
                "evidence only; report property_mismatch without rejecting an otherwise valid match. "
                "For example, Component/auth service and Service/authentication service may match with "
                "label_mismatch, whereas auth service and log service are not equivalent just because "
                "both have the Service label."
            ),
            "triple": (
                "Match the same directed fact: out_v and in_v must correspond separately and direction "
                "must agree. Relation aliases may match with relation_mismatch; different facts may not. "
                "Differences in out_v_label/in_v_label are soft endpoint_label_mismatch issues. Property "
                "differences are soft property_mismatch issues. For example, A DEPENDS_ON B and A REQUIRES B "
                "may match, but B REQUIRES A reverses the fact and must not match."
            ),
        }[kind]
        protocol = (
            "candidates is the current candidate window; references is the complete reference graph. "
            "For every reference_index, return ALL semantically valid candidate pairs in this window. "
            "Do not keep only the best candidate and do not assign one-to-one within a window. "
            "Both reference_index and candidate_index may occur in multiple distinct pairs. The caller "
            "selects a maximum-total-weight one-to-one matching over all pairs from all windows. "
            "Each (reference_index, candidate_index) pair must be unique. Only when a reference has no "
            "valid candidate in this window, return exactly one null candidate_index for it; never mix "
            "a null verdict with matched pairs for the same reference. Cover every reference and use "
            "only supplied global indices. Matched pairs require match_score in [0, 100]; unmatched "
            "verdicts require match_score=null and no_semantic_match. Give a concrete reason grounded "
            "in the supplied names, relation, direction or properties; do not invent evidence."
        )
        output_rule = "Return only JSON in this shape; the illustrative indices show alternative pairs:"
    issues = {
        "entity": "label_mismatch, property_mismatch, name_mismatch, no_semantic_match",
        "triple": (
            "relation_mismatch, endpoint_label_mismatch, endpoint_mismatch, direction_mismatch, "
            "property_mismatch, no_semantic_match"
        ),
    }[kind]
    return f"""{rules}

{protocol}

Allowed match_issues: {issues}. Use [] when none apply. name_mismatch,
endpoint_mismatch and direction_mismatch are hard conflicts: never put them on
an accepted pair. Use no_semantic_match only on an unmatched reference verdict.

{output_rule}
{{
  "verdicts": [
    {{"reference_index": 0, "candidate_index": 12, "match_score": 88, "match_issues": [], "reason": "Evidence for pair 0/12"}},
    {{"reference_index": 0, "candidate_index": 13, "match_score": 92, "match_issues": [], "reason": "Evidence for alternative 0/13"}},
    {{"reference_index": 1, "candidate_index": 12, "match_score": 86, "match_issues": [], "reason": "Evidence for alternative 1/12"}},
    {{"reference_index": 2, "candidate_index": null, "match_score": null, "match_issues": ["no_semantic_match"], "reason": "No valid candidate in this window"}}
  ]
}}"""
