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

"""Real LLM-based judge using a BaseLLM instance for scoring.

Framework implementation - specific prompts and parsing logic
to be extended as needed.
"""

import json
import logging
from typing import Any, Dict, Optional

from hugegraph_llm.benchmark.llm_judge.base import LLMJudge

logger = logging.getLogger(__name__)

_DEFAULT_JUDGE_PROMPT = """\
You are an expert evaluator. Given a question, context, and an answer, \
rate the answer's correctness on a scale from 0.0 to 1.0.

Question: {question}

Context: {context}

Answer: {answer}

Respond with a JSON object containing exactly two fields:
- "score": a float between 0.0 and 1.0
- "reason": a brief explanation of your rating
"""


class RealLLMJudge(LLMJudge):
    """LLM-based judge that uses a BaseLLM instance for evaluation.

    Accepts any object implementing the BaseLLM interface (with a
    `generate` or `chat` method). The prompt template can be customized.
    """

    def __init__(self, llm: Any, prompt_template: Optional[str] = None):
        """Initialize the real LLM judge.

        Args:
            llm: A BaseLLM-compatible instance with a generate/chat method.
            prompt_template: Optional custom prompt template with
                {question}, {answer}, {context} placeholders.
        """
        self._llm = llm
        self._prompt_template = prompt_template or _DEFAULT_JUDGE_PROMPT

    def judge(
        self,
        question: str,
        answer: str,
        context: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Use the LLM to judge answer quality.

        Args:
            question: The original question.
            answer: The answer to evaluate.
            context: Additional context (e.g., retrieved passages).
            **kwargs: Extra parameters forwarded to the LLM call.

        Returns:
            Dict with 'score' (float) and 'reason' (str).
        """
        prompt = self._prompt_template.format(
            question=question,
            answer=answer,
            context=context,
        )

        try:
            response = self._call_llm(prompt, **kwargs)
            return self._parse_response(response)
        except Exception as e:
            logger.warning("LLM judge failed: %s", e)
            return {"score": 0.0, "reason": f"judge_error: {e}"}

    def _call_llm(self, prompt: str, **kwargs: Any) -> str:
        """Call the LLM with the judge prompt.

        Supports both `generate(prompt)` and `chat(messages)` interfaces.
        """
        if hasattr(self._llm, "generate"):
            return self._llm.generate(prompt, **kwargs)
        elif hasattr(self._llm, "chat"):
            messages = [{"role": "user", "content": prompt}]
            return self._llm.chat(messages, **kwargs)
        else:
            raise AttributeError(f"LLM instance {type(self._llm).__name__} has no 'generate' or 'chat' method")

    @staticmethod
    def _parse_response(response: str) -> Dict[str, Any]:
        """Parse the LLM response into score and reason.

        Expects JSON with 'score' and 'reason' fields. Falls back to
        default values if parsing fails.
        """
        # Try to extract JSON from the response
        text = response.strip()

        # Handle markdown code blocks
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    data = json.loads(part)
                    if isinstance(data, dict) and "score" in data:
                        return {
                            "score": float(data["score"]),
                            "reason": str(data.get("reason", "")),
                        }
                except (json.JSONDecodeError, ValueError):
                    continue

        # Try direct JSON parse
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "score" in data:
                return {
                    "score": float(data["score"]),
                    "reason": str(data.get("reason", "")),
                }
        except (json.JSONDecodeError, ValueError):
            pass

        logger.warning("Could not parse LLM judge response: %s", text[:200])
        return {"score": 0.0, "reason": f"parse_error: {text[:200]}"}
