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
    """Adapt the historical semantic-matching few-shot prompt to batched verdicts."""
    prompt_name = {
        "entity": "ENTITY_SEMANTIC_MATCH_PROMPT",
        "triple": "TRIPLE_SEMANTIC_MATCH_PROMPT",
    }.get(kind)
    if prompt_name is None:
        raise ValueError(f"Unsupported semantic graph item kind: {kind}")
    historical = get_prompt(prompt_name, language)
    rule_override = {
        "entity": (
            "当前运行时实体匹配规则覆盖上面的历史规则：即使 label 不一致，只要 candidate.name 与 reference.name"
            " 语义等价，也必须判定为命中，返回 candidate_index，并在 match_issues 中加入 label_mismatch；"
            "不得仅因 label 不一致返回 candidate_index=null。"
        ),
        "triple": (
            "当前运行时关系边匹配规则覆盖上面的历史规则。关系边表示一条有方向的事实，必须同时判断关系类型、"
            "起点端点、终点端点和方向。关系类型只是名称表达：如果候选关系类型与标准关系类型是同义词、别名、"
            "缩写或不同表述但表达同一个事实关系，必须判定为命中，并加入 relation_mismatch；只有表达了不同事实"
            "时才不得命中。起点 out_v 和终点 in_v 的名称需要分别语义对应；端点名称不对应时不得命中，并加入"
            " endpoint_mismatch。out_v_label 和 in_v_label 只是端点类型的辅助信息：端点名称对应但类型不同仍可"
            "判定为命中，并加入 endpoint_label_mismatch，不得仅因端点类型不同否决。方向是硬条件：候选 out_v 必须"
            "对应标准 out_v，候选 in_v 必须对应标准 in_v；反向边不得命中，并加入 direction_mismatch 和"
            " no_semantic_match。边 properties 只作辅助证据，属性差异不影响关系命中，但必须在 reason 中具体说明。"
        ),
    }[kind]
    reason_guidance = {
        "entity": (
            "实体匹配以 label 和 name 为主；properties 中的属性名和值只作辅助证据，不要求所有属性完全一致。"
            "命中时，reason 必须具体说明类型是否一致、候选名称与标准名称为何等价（例如全称/缩写/同义表达），"
            "如果属性名或属性值存在差异，必须写出具体属性名和简短差异摘要，并明确说明“不影响实体匹配”；"
            "属性差异本身不能否决命中，也不能作为未命中的唯一理由；不能只写“语义等价”。实体未命中时，必须说明类型或名称不匹配的具体原因；"
            "如果窗口中有最接近候选，写出其 candidate_index 和冲突字段，否则明确写“无近似候选”。"
        ),
        "triple": (
            "关系命中时，reason 必须具体说明：关系类型是否相同或为何语义等价、起点和终点是否分别对应、端点"
            "类型是否一致或存在差异、方向是否一致，以及关键属性是否一致或存在差异；不能只写“语义等价”。"
            "如果关系类型或端点类型存在差异但仍命中，必须说明这是名称表达或类型标注差异，不影响关系事实匹配。"
            "关系未命中时，必须说明是端点不对应、方向相反还是关系类型表达了不同事实；如果窗口中有最接近关系，"
            "写出其 candidate_index 和冲突字段，否则明确写“无近似候选”。"
        ),
    }[kind]
    reason_examples = {
        "entity": (
            "命中示例：“类型不一致但名称语义匹配；候选名称“认证服务超时指示灯”与标准名称“认证超时告警”匹配；名称为全称和缩写对应；属性差异：description（表述不同）；不影响实体匹配。”；"
            "未命中示例：“未命中；最接近候选=23；名称相近但类型为 Warning、标准答案类型为 Feature。”"
        ),
        "triple": (
            "命中示例：“关系类型名称不同但事实语义等价（候选 HAS_COMPONENT，标准声明依赖）；起点和终点分别对应同一服务和网关服务；端点类型一致；方向一致；属性差异：description（表述不同）；不影响关系匹配。”；"
            "未命中示例：“未命中；最接近候选=23；关系类型语义一致但终点名称不对应且方向相反。”"
        ),
    }[kind]
    issue_guidance = {
        "entity": (
            "match_issues 必须是以下分类的数组：label_mismatch、property_mismatch、name_mismatch、"
            "no_semantic_match。名称和语义匹配但类型不同，仍然算命中，并返回 label_mismatch；"
            "属性不同只返回 property_mismatch，不得因此返回 no_semantic_match。完全没有问题时返回空数组。"
        ),
        "triple": (
            "match_issues 必须是以下分类的数组：relation_mismatch、endpoint_label_mismatch、endpoint_mismatch、"
            "direction_mismatch、property_mismatch、no_semantic_match。关系类型只是别名或表述差异但事实语义"
            "相同时，命中并列出 relation_mismatch；端点名称对应但端点类型不同，命中并列出"
            " endpoint_label_mismatch；属性不同只列出 property_mismatch。endpoint_mismatch 或 direction_mismatch"
            "表示硬冲突，必须同时返回 candidate_index=null 和 no_semantic_match。完全没有问题时返回空数组。"
        ),
    }[kind]
    matched_reason_example, unmatched_reason_example = {
        "entity": (
            "类型不一致但名称语义匹配；候选名称“认证服务超时指示灯”与标准名称“认证超时告警”匹配；名称为全称和缩写对应；属性差异：description（表述不同）；不影响实体匹配。",
            "未命中；最接近候选=23；名称相近但类型不一致。",
        ),
        "triple": (
            "关系类型名称不同但事实语义等价；起点和终点对应；端点类型一致；方向一致；关键属性无冲突。",
            "未命中；最接近候选=23；关系类型语义一致但终点不对应且方向相反。",
        ),
    }[kind]
    return f"""{historical}

---

当前批处理协议覆盖上面的旧输出格式：candidates 是本次候选窗口，references
是完整文档标准答案。对每一个 reference_index，必须在当前 candidates 窗口中找至多
一个语义等价候选；若当前窗口没有命中，则 candidate_index 必须为 null。不同候选
窗口会重复判断同一个 reference，后处理阶段再做全局一对一去重。
同一个 candidate_index 不能匹配多个 reference_index。
{rule_override}

{reason_guidance}
{reason_examples}
{issue_guidance}

只返回下列 JSON 对象，且 verdicts 中必须恰好有一项对应每个 reference_index。命中时
必须给出 0 到 100 的 match_score，数值越大表示语义匹配置信度越高；未命中时
match_score 必须为 null：
{{
  "verdicts": [
    {{"reference_index": 0, "candidate_index": 12, "match_score": 88, "match_issues": ["label_mismatch", "property_mismatch"], "reason": "{matched_reason_example}"}},
    {{"reference_index": 1, "candidate_index": null, "match_score": null, "match_issues": ["no_semantic_match"], "reason": "{unmatched_reason_example}"}}
  ]
}}

candidate_index 必须是当前 candidates 中显示的全局索引。reason 必须简短、具体，并严格依据输入内容，
不得编造输入中不存在的属性或证据。
不得返回 matches、reasoning 或任何其他键。"""
