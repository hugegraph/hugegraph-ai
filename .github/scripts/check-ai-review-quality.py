#!/usr/bin/env python3
#
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

"""Decide whether an AI PR review should be retried.

The script intentionally depends only on GitHub API JSON files and the Python
standard library, so the decision logic is testable locally without invoking
the reviewer bot.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_REVIEWER_LOGINS = ("codecov-ai-reviewer", "codecov-ai-reviewer[bot]")
DEFAULT_MIN_CHARS = 800
DEFAULT_MAX_RETRIES = 2
TRIGGER_MARKER = "ai-review-watchdog:trigger"
RETRY_COUNT_PATTERN = re.compile(r"ai-review-watchdog:retry-count=(\d+)")
SHORT_ONLY_PATTERN = re.compile(
    r"^\s*(lgtm|looks good|looks good to me|no issues found|approved|ok|ship it)[.!]?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReviewOutput:
    body: str
    source: str
    created_at: str


def main() -> int:
    args = _parse_args()
    comments = _load_json_array(args.comments) if args.comments else []
    reviews = _load_json_array(args.reviews) if args.reviews else []

    result = evaluate_review_quality(
        comments=comments,
        reviews=reviews,
        reviewer_logins=tuple(args.reviewer_login),
        min_chars=args.min_chars,
        max_retries=args.max_retries,
    )
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0


def evaluate_review_quality(
    *,
    comments: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    reviewer_logins: tuple[str, ...] = DEFAULT_REVIEWER_LOGINS,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict[str, Any]:
    retry_count = _max_retry_count(comments)
    latest_trigger_time = _latest_trigger_time(comments)
    outputs = _reviewer_outputs(comments, reviews, set(reviewer_logins), since=latest_trigger_time)

    if retry_count >= max_retries:
        return _decision(
            needs_retry=False,
            reason="max_retries_reached",
            retry_count=retry_count,
            review_count=len(outputs),
            max_retries=max_retries,
        )

    if not outputs:
        return _decision(
            needs_retry=True,
            reason="missing_review",
            retry_count=retry_count,
            review_count=0,
            max_retries=max_retries,
        )

    latest = max(outputs, key=lambda output: output.created_at or "")
    normalized_body = _normalize_body(latest.body)
    if SHORT_ONLY_PATTERN.fullmatch(normalized_body):
        return _decision(
            needs_retry=True,
            reason="review_too_shallow",
            retry_count=retry_count,
            review_count=len(outputs),
            max_retries=max_retries,
            latest_chars=len(normalized_body),
            latest_source=latest.source,
        )

    if len(normalized_body) < min_chars:
        return _decision(
            needs_retry=True,
            reason="review_too_short",
            retry_count=retry_count,
            review_count=len(outputs),
            max_retries=max_retries,
            latest_chars=len(normalized_body),
            latest_source=latest.source,
        )

    return _decision(
        needs_retry=False,
        reason="review_present",
        retry_count=retry_count,
        review_count=len(outputs),
        max_retries=max_retries,
        latest_chars=len(normalized_body),
        latest_source=latest.source,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comments", type=Path, help="GitHub issue comments JSON")
    parser.add_argument("--reviews", type=Path, help="GitHub PR reviews JSON")
    parser.add_argument(
        "--reviewer-login",
        action="append",
        default=list(DEFAULT_REVIEWER_LOGINS),
        help="Reviewer login to treat as the AI reviewer. May be repeated.",
    )
    parser.add_argument("--min-chars", type=int, default=DEFAULT_MIN_CHARS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    return parser.parse_args()


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def _reviewer_outputs(
    comments: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    reviewer_logins: set[str],
    *,
    since: str,
) -> list[ReviewOutput]:
    outputs: list[ReviewOutput] = []
    for comment in comments:
        created_at = str(comment.get("created_at") or "")
        updated_at = str(comment.get("updated_at") or created_at)
        if _login(comment) in reviewer_logins and _is_after_trigger(updated_at, since):
            outputs.append(
                ReviewOutput(
                    body=str(comment.get("body") or ""),
                    source="comment",
                    created_at=updated_at,
                )
            )
    for review in reviews:
        created_at = str(review.get("submitted_at") or review.get("created_at") or "")
        if _login(review) in reviewer_logins and _is_after_trigger(created_at, since):
            outputs.append(
                ReviewOutput(
                    body=str(review.get("body") or ""),
                    source="review",
                    created_at=created_at,
                )
            )
    return outputs


def _login(item: dict[str, Any]) -> str:
    user = item.get("user")
    if isinstance(user, dict):
        return str(user.get("login") or "")
    return ""


def _max_retry_count(comments: list[dict[str, Any]]) -> int:
    max_count = 0
    for comment in comments:
        body = str(comment.get("body") or "")
        for match in RETRY_COUNT_PATTERN.finditer(body):
            max_count = max(max_count, int(match.group(1)))
    return max_count


def _latest_trigger_time(comments: list[dict[str, Any]]) -> str:
    latest = ""
    for comment in comments:
        body = str(comment.get("body") or "")
        if TRIGGER_MARKER not in body:
            continue
        created_at = str(comment.get("created_at") or "")
        updated_at = str(comment.get("updated_at") or created_at)
        latest = max(latest, updated_at)
    return latest


def _is_after_trigger(created_at: str, trigger_time: str) -> bool:
    return not trigger_time or not created_at or created_at >= trigger_time


def _normalize_body(body: str) -> str:
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    body = re.sub(r"\s+", " ", body)
    return body.strip()


def _decision(**kwargs: Any) -> dict[str, Any]:
    return {
        "needs_retry": kwargs["needs_retry"],
        "reason": kwargs["reason"],
        "retry_count": kwargs["retry_count"],
        "next_retry_count": kwargs["retry_count"] + 1 if kwargs["needs_retry"] else kwargs["retry_count"],
        "max_retries": kwargs["max_retries"],
        "review_count": kwargs["review_count"],
        "latest_chars": kwargs.get("latest_chars", 0),
        "latest_source": kwargs.get("latest_source"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
