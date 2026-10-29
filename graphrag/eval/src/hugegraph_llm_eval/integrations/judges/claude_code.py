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

"""Judge backed by the Claude Code CLI, so evaluation can run on a Claude subscription."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import weakref
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from typing import Protocol

from pydantic import JsonValue, ValidationError

from hugegraph_llm_eval.contracts.domain.judge import ProviderUsage
from hugegraph_llm_eval.contracts.errors import FailureCategory, FailureDetail
from hugegraph_llm_eval.evaluation.judges.base import JudgeDescriptor, JudgeRequest, OutputT
from hugegraph_llm_eval.integrations.judges.attempts import (
    AttemptFailureError,
    AttemptLoopJudge,
    AttemptOutcome,
    failure,
)
from hugegraph_llm_eval.integrations.judges.cli_common import cli_version, split_messages, token_count
from hugegraph_llm_eval.utils.clock import utc_now

PROVIDER = "claude-code"
_MAX_SYSTEM_PROMPT_BYTES = 100_000
_PROVIDER_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_")
_USAGE_LIMIT_MARKERS = ("usage limit", "limit reached", "limit will reset")
_PROTECTED_EXTRA_FLAGS = frozenset(
    {
        "--tools",
        "--setting-sources",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--json-schema",
        "--model",
        "--output-format",
        "--permission-mode",
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--mcp-config",
    }
)


class ProcessRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        prompt: str,
        env: Mapping[str, str],
        cwd: str,
        timeout: float,
    ) -> "subprocess.CompletedProcess[str]": ...


def _run_process(
    argv: Sequence[str],
    *,
    prompt: str,
    env: Mapping[str, str],
    cwd: str,
    timeout: float,
) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        list(argv),
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=dict(env),
        cwd=cwd,
        timeout=timeout,
    )


class ClaudeCodeJudge(AttemptLoopJudge):
    """Runs each Judge call as one tool-free headless ``claude -p`` process.

    Authenticates as the CLI does in your terminal; ``scrub_provider_env=True`` with
    ``setting_sources=""`` forces the logged-in subscription.
    """

    def __init__(
        self,
        *,
        model: str,
        effort: str | None = None,
        executable: str = "claude",
        setting_sources: str | None = None,
        scrub_provider_env: bool = False,
        max_turns: int | None = None,
        extra_args: Sequence[str] = (),
        call_timeout_seconds: float = 600.0,
        version: str | None = None,
        clock: Callable[[], datetime] = utc_now,
        runner: ProcessRunner = _run_process,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if call_timeout_seconds <= 0:
            msg = "call_timeout_seconds must be positive"
            raise ValueError(msg)
        if max_turns is not None and max_turns < 1:
            msg = "max_turns must be at least 1"
            raise ValueError(msg)
        conflicts = sorted({arg.split("=", 1)[0] for arg in extra_args} & _PROTECTED_EXTRA_FLAGS)
        if conflicts:
            raise ValueError(f"extra_args cannot override controlled Claude CLI flags: {', '.join(conflicts)}")
        configuration: JsonValue = {
            "cli_version": version if version is not None else cli_version(executable),
            "effort": effort,
            "setting_sources": setting_sources,
            "scrub_provider_env": scrub_provider_env,
            "max_turns": max_turns,
            "extra_args": list(extra_args),
            "tools": "disabled",
            "sampling": "provider-controlled",
        }
        super().__init__(
            descriptor=JudgeDescriptor.create(provider=PROVIDER, model=model, configuration=configuration),
            clock=clock,
            monotonic=monotonic,
            sleep=sleep,
        )
        self._executable = executable
        self._effort = effort
        self._setting_sources = setting_sources
        self._scrub_provider_env = scrub_provider_env
        self._max_turns = max_turns
        self._extra_args = tuple(extra_args)
        self._call_timeout = call_timeout_seconds
        self._runner = runner
        self._workdir = tempfile.mkdtemp(prefix="hugegraph-llm-eval-claude-")
        weakref.finalize(self, shutil.rmtree, self._workdir, ignore_errors=True)

    def _argv(self, request: JudgeRequest[OutputT], system: str | None) -> list[str]:
        schema = json.dumps(request.response_type.model_json_schema(), separators=(",", ":"), sort_keys=True)
        argv = [
            self._executable,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--model",
            self.descriptor.model,
            "--tools",
            "",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--strict-mcp-config",
        ]
        if self._setting_sources is not None:
            argv += ["--setting-sources", self._setting_sources]
        if self._effort is not None:
            argv += ["--effort", self._effort]
        if self._max_turns is not None:
            argv += ["--max-turns", str(self._max_turns)]
        if system is not None:
            argv += ["--system-prompt", system]
        return [*argv, *self._extra_args]

    def _environment(self) -> dict[str, str]:
        if not self._scrub_provider_env:
            return dict(os.environ)
        return {key: value for key, value in os.environ.items() if not key.startswith(_PROVIDER_ENV_PREFIXES)}

    def _attempt(self, request: JudgeRequest[OutputT], timeout: float | None) -> AttemptOutcome:
        system, prompt = split_messages(request)
        if system is not None and len(system.encode("utf-8")) > _MAX_SYSTEM_PROMPT_BYTES:
            system, prompt = None, f"{system}\n\n{prompt}"
        limit = self._call_timeout if timeout is None else min(timeout, self._call_timeout)
        completed = self._runner(
            self._argv(request, system),
            prompt=prompt,
            env=self._environment(),
            cwd=self._workdir,
            timeout=limit,
        )
        return self._outcome(request, completed)

    def _classify(self, error: Exception) -> FailureDetail:
        if isinstance(error, subprocess.TimeoutExpired):
            return failure(FailureCategory.TIMEOUT, "provider_timeout", True)
        if isinstance(error, FileNotFoundError):
            return failure(FailureCategory.PROVIDER_UNAVAILABLE, "executable_not_found", False)
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_transport_error", False)

    def _outcome(
        self,
        request: JudgeRequest[OutputT],
        completed: "subprocess.CompletedProcess[str]",
    ) -> AttemptOutcome:
        payload = _parse_payload(completed.stdout)
        if payload is None:
            code = "malformed_provider_response" if completed.returncode == 0 else "provider_process_failed"
            raise AttemptFailureError(failure(FailureCategory.INVALID_PROVIDER_OUTPUT, code, False))
        usage = self._usage(payload)
        if payload.get("is_error") or completed.returncode != 0:
            raise AttemptFailureError(_error_detail(payload), usage=usage)
        structured = _structured_output(payload)
        if structured is None:
            detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "missing_structured_output", True)
            raise AttemptFailureError(detail, usage=usage)
        try:
            output = request.response_type.model_validate(structured)
        except ValidationError as exc:
            detail = failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "invalid_structured_output", True)
            raise AttemptFailureError(detail, usage=usage) from exc
        models = payload.get("modelUsage")
        session_id = payload.get("session_id")
        return AttemptOutcome(
            output=output,
            usage=usage,
            response_id=session_id if isinstance(session_id, str) else None,
            response_model=next(iter(models)) if isinstance(models, dict) and len(models) == 1 else None,
        )

    def _usage(self, payload: dict[str, object]) -> ProviderUsage:
        raw = payload.get("usage")
        if not isinstance(raw, dict):
            return self._unreported_usage()
        input_keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        return self._usage_from_tokens(
            sum(token_count(raw, key) for key in input_keys),
            token_count(raw, "output_tokens"),
        )


def _parse_payload(stdout: str) -> dict[str, object] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _structured_output(payload: dict[str, object]) -> object | None:
    structured = payload.get("structured_output")
    result = payload.get("result")
    if structured is None and isinstance(result, str):
        with suppress(json.JSONDecodeError):
            return json.loads(result)
    return structured


def _error_detail(payload: dict[str, object]) -> FailureDetail:
    raw_status = payload.get("api_error_status")
    status = raw_status if isinstance(raw_status, int) else None
    text = str(payload.get("result") or "").lower()
    if "not logged in" in text or status in (401, 403):
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_not_authenticated", False)
    if any(marker in text for marker in _USAGE_LIMIT_MARKERS):
        return failure(FailureCategory.PROVIDER_RATE_LIMIT, "provider_usage_limit", False)
    if status == 429 or "rate limit" in text:
        return failure(FailureCategory.PROVIDER_RATE_LIMIT, "provider_rate_limit", True)
    if status is not None and status >= 500:
        return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_unavailable", True)
    if payload.get("subtype") == "error_max_turns":
        return failure(FailureCategory.INVALID_PROVIDER_OUTPUT, "max_turns_exceeded", True)
    return failure(FailureCategory.PROVIDER_UNAVAILABLE, "provider_request_rejected", False)
