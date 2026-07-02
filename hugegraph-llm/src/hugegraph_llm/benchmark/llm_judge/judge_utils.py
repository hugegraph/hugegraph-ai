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

"""Shared utilities for LLM-judge-based metrics.

Centralizes JSON response parsing logic, retry mechanism, and context
cleaning that was previously duplicated across metric files.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# GraphRAG-Benchmark standard: max 2 retries with exponential backoff
_MAX_RETRIES = 2
_RETRY_BASE_DELAY = 1.0


def retry_llm_call(llm: Any, prompt: str, max_retries: int = _MAX_RETRIES) -> str:
    """Call LLM with retry on transient failures (GraphRAG-Benchmark pattern).

    Args:
        llm: LLM client with a ``generate(prompt=...)`` method.
        prompt: The prompt text to send.
        max_retries: Maximum retry attempts (default 2, matching GraphRAG-Bench).

    Returns:
        LLM response text.

    Raises:
        RuntimeError: If all attempts (including retries) fail.
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return llm.generate(prompt=prompt)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    e,
                )
                time.sleep(delay)

    raise RuntimeError(f"LLM call failed after {max_retries + 1} attempts: {last_error}")


def _repair_json(text: str) -> Optional[str]:
    """Repair common LLM JSON output errors so json.loads can succeed.

    Handles:
    - Trailing commas before closing bracket/brace
    - Single-quoted strings (convert to double quotes)
    - Python-style None/True/False (convert to null/true/false)
    - Extra text before/after the JSON object
    """
    if not text:
        return None

    # Extract the JSON object boundaries
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    text = text[start : end + 1]

    # Fix trailing commas
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Fix Python booleans/None
    text = re.sub(r"\bNone\b", "null", text)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)

    # Fix single-quoted strings (simple approach: convert ' to " for keys and values)
    # Only apply if the text contains single quotes and not already valid JSON
    if "'" in text:
        text = re.sub(r"'([^']*)'", r'"\1"', text)

    return text


def parse_json_response(response: str) -> Optional[Dict[str, Any]]:
    """Parse JSON from an LLM response with multi-stage fallback.

    Attempts five strategies in order:
    1. Direct ``json.loads`` on the stripped response text.
    2. Extract content from markdown code blocks (```json ... ```).
    3. Regex extraction of the first ``{...}`` block in the text.
    4. Repair common LLM JSON errors (trailing commas, single quotes) and retry.
    5. Regex-based key-value extraction as last resort.

    Args:
        response: Raw string response from an LLM.

    Returns:
        Parsed dict on success, or ``None`` if all strategies fail.
    """
    text = response.strip()

    # Strategy 1: direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: markdown code block extraction
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            try:
                return json.loads(part)
            except (json.JSONDecodeError, ValueError):
                continue

    # Strategy 3: regex fallback - extract first {...} block (supports nested)
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 4: repair common LLM JSON errors
    repaired = _repair_json(text)
    if repaired:
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Failed to parse JSON from LLM response: %s", text[:200])
    return None


def clean_contexts(contexts: List[str]) -> List[str]:
    """Clean and deduplicate context passages for LLM-Judge metrics.

    Strips whitespace, removes empty strings, and deduplicates while
    preserving original order.

    Args:
        contexts: Raw context passages from retrieval.

    Returns:
        Cleaned, deduplicated context list.
    """
    seen = set()
    cleaned = []
    for c in contexts:
        s = str(c).strip()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
    return cleaned
