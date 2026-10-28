# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run provider contracts when their optional extras are explicitly installed."""

import asyncio
import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from hugegraph_llm_core.errors import LLMOutputTruncatedError

PRIVATE_PAYLOAD = "synthetic-private-key-and-provider-echo"


@pytest.fixture(params=["openai", "ollama", "litellm"])
def provider(request, monkeypatch):
    name = request.param
    pytest.importorskip(name, reason=f"Install hugegraph-llm-core[{name}] to run this provider contract")
    module = importlib.import_module(f"hugegraph_llm_core.providers.{name}")
    sync_call, async_call = Mock(), AsyncMock()
    if name == "openai":
        client = module.OpenAIClient(
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=sync_call))),
            async_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=async_call))),
        )
    elif name == "ollama":
        monkeypatch.setattr(module.ollama, "Client", lambda **_: SimpleNamespace(chat=sync_call))
        monkeypatch.setattr(module.ollama, "AsyncClient", lambda **_: SimpleNamespace(chat=async_call))
        client = module.OllamaClient(model="unit-model")
    else:
        monkeypatch.setattr(module, "completion", sync_call)
        monkeypatch.setattr(module, "acompletion", async_call)
        client = module.LiteLLMClient(model_name="openai/unit-model", api_key="unit-key")
    return name, client, sync_call, async_call


def response(name, *, content="complete", reason="stop"):
    if name == "ollama":
        return {
            "message": {"content": content},
            "done_reason": reason,
            "prompt_eval_count": 1,
            "eval_count": 1,
        }
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=reason)],
        usage=None,
    )


def invoke(client, mode):
    if mode == "async":
        return asyncio.run(client.agenerate(prompt="input text"))
    return client.generate(prompt="input text")


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_provider_defaults_reject_truncation(provider, mode):
    name, client, sync_call, async_call = provider
    call = async_call if mode == "async" else sync_call
    call.return_value = response(name, content="partial private content", reason="length")

    with pytest.raises(LLMOutputTruncatedError) as caught:
        invoke(client, mode)

    assert "private" not in str(caught.value)
    assert caught.value.reason == ("done_reason=length" if name == "ollama" else "finish_reason=length")
    call.assert_called_once()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_provider_defaults_preserve_output_and_do_not_set_a_cap(provider, mode):
    name, client, sync_call, async_call = provider
    call = async_call if mode == "async" else sync_call
    call.return_value = response(name)

    assert invoke(client, mode) == "complete"
    call.assert_called_once()
    assert call.call_args.kwargs["messages"] == [{"role": "user", "content": "input text"}]
    if name == "litellm":
        assert call.call_args.kwargs["max_tokens"] is None  # LiteLLM's adapter owns None omission.
    else:
        assert "max_tokens" not in call.call_args.kwargs


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_provider_does_not_retry_programming_errors(provider, mode):
    _, client, sync_call, async_call = provider
    call = async_call if mode == "async" else sync_call
    failure = ValueError("invalid provider input")
    call.side_effect = failure
    with pytest.raises(ValueError) as caught:
        invoke(client, mode)
    assert caught.value is failure
    call.assert_called_once()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_openai_default_raises_authentication_errors(mode):
    openai = pytest.importorskip("openai", reason="Install the openai extra to run this provider contract")
    httpx = pytest.importorskip("httpx")
    from hugegraph_llm_core.providers.openai import OpenAIClient

    error = openai.AuthenticationError(
        "invalid key", response=httpx.Response(401, request=httpx.Request("POST", "https://model.invalid")), body=None
    )
    sync_call, async_call = Mock(side_effect=error), AsyncMock(side_effect=error)
    client = OpenAIClient(
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=sync_call))),
        async_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=async_call))),
    )
    with pytest.raises(openai.AuthenticationError) as caught:
        invoke(client, mode)
    assert caught.value is error
    (async_call if mode == "async" else sync_call).assert_called_once()


def test_new_and_legacy_clients_share_transport_without_changing_legacy_defaults():
    pytest.importorskip("openai", reason="Install the openai extra to run this provider contract")
    pytest.importorskip("hugegraph_llm", reason="Legacy compatibility is also exercised by the application suite")
    from hugegraph_llm.models.llms.base import BaseLLM
    from hugegraph_llm.models.llms.base import LLMOutputTruncatedError as LegacyTruncationError
    from hugegraph_llm.models.llms.openai import OpenAIClient as LegacyClient
    from hugegraph_llm_core.providers.openai import OpenAIClient

    assert issubclass(LegacyClient, BaseLLM)
    assert LegacyClient.generate is OpenAIClient.generate
    assert LegacyClient.agenerate is OpenAIClient.agenerate
    assert LegacyTruncationError is LLMOutputTruncatedError


@pytest.fixture(params=["openai", "ollama"])
def managed_provider(request, monkeypatch):
    name = request.param
    pytest.importorskip(name, reason=f"Install hugegraph-llm-core[{name}] to run this provider contract")
    module = importlib.import_module(f"hugegraph_llm_core.providers.{name}")
    close, aclose = Mock(), AsyncMock()
    if name == "openai":
        client = module.OpenAIClient(client=SimpleNamespace(close=close), async_client=SimpleNamespace(close=aclose))
    else:
        monkeypatch.setattr(module.ollama, "Client", lambda **_: SimpleNamespace(_client=SimpleNamespace(close=close)))
        monkeypatch.setattr(
            module.ollama, "AsyncClient", lambda **_: SimpleNamespace(_client=SimpleNamespace(aclose=aclose))
        )
        client = module.OllamaClient(model="unit-model")
    return client, close, aclose


def test_provider_close_only_closes_sync_transport(managed_provider):
    client, close, aclose = managed_provider
    client.close()
    close.assert_called_once_with()
    aclose.assert_not_called()


def test_provider_aclose_closes_both_transports(managed_provider):
    client, close, aclose = managed_provider
    asyncio.run(client.aclose())
    close.assert_called_once_with()
    aclose.assert_awaited_once_with()


def test_provider_async_close_failure_still_closes_sync_transport(managed_provider):
    client, close, aclose = managed_provider
    failure = RuntimeError("async close failed")
    aclose.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(client.aclose())
    assert caught.value is failure
    close.assert_called_once_with()
    aclose.assert_awaited_once_with()


def invoke_mode(client, mode):
    if mode in ("sync", "async"):
        return invoke(client, mode)
    if mode == "stream":
        output = client.generate_streaming(prompt="input text")
        return output if isinstance(output, str) else "".join(output)

    async def collect():
        return "".join([part async for part in client.agenerate_streaming(prompt="input text")])

    return asyncio.run(collect())


@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
def test_provider_failure_logs_do_not_include_error_content(provider, mode, caplog, monkeypatch):
    name, client, sync_call, async_call = provider
    if name == "ollama":
        import httpx
        from tenacity import stop_after_attempt

        failure = httpx.ConnectError(PRIVATE_PAYLOAD)
        # Exercise the real diagnostic path without retry delays; retry counts
        # remain covered by the existing provider and application contracts.
        for method in (client.generate, client.agenerate):
            monkeypatch.setattr(method.retry, "stop", stop_after_attempt(1))
            monkeypatch.setattr(method.retry, "reraise", True)
    elif name == "litellm":
        from litellm.exceptions import BudgetExceededError

        failure = BudgetExceededError(current_cost=2.0, max_budget=1.0, message=PRIVATE_PAYLOAD)
    else:
        failure = ValueError(PRIVATE_PAYLOAD)
    call = async_call if mode.startswith("async") else sync_call
    call.side_effect = failure
    caplog.set_level(logging.DEBUG, logger=f"hugegraph_llm_core.providers.{name}")

    with pytest.raises(type(failure)) as caught:
        invoke_mode(client, mode)

    assert caught.value is failure
    assert PRIVATE_PAYLOAD not in caplog.text
    if name != "ollama" or mode != "stream":
        assert type(failure).__name__ in caplog.text


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_provider_usage_logs_only_numeric_counter_fields(provider, mode, caplog):
    name, client, sync_call, async_call = provider
    returned = response(name, content=PRIVATE_PAYLOAD)
    if name == "ollama":
        returned.update(prompt_eval_count=3, eval_count=PRIVATE_PAYLOAD, vendor_extra=PRIVATE_PAYLOAD)
    else:
        returned.usage = SimpleNamespace(
            prompt_tokens=3,
            completion_tokens=PRIVATE_PAYLOAD,
            total_tokens=5,
            vendor_extra=PRIVATE_PAYLOAD,
            model_dump_json=lambda: PRIVATE_PAYLOAD,
        )
    (async_call if mode == "async" else sync_call).return_value = returned
    caplog.set_level(logging.DEBUG, logger=f"hugegraph_llm_core.providers.{name}")

    assert invoke(client, mode) == PRIVATE_PAYLOAD
    assert "prompt_tokens" in caplog.text and "3" in caplog.text
    assert "completion_tokens" not in caplog.text
    assert "vendor_extra" not in caplog.text
    assert PRIVATE_PAYLOAD not in caplog.text


@pytest.mark.parametrize("mode", ["stream", "async_stream"])
def test_provider_stream_diagnostics_do_not_log_response_chunks(provider, mode, caplog):
    name, client, sync_call, async_call = provider
    if name == "ollama":
        chunks = [
            {"message": {}, "vendor_extra": PRIVATE_PAYLOAD},
            {"message": {"content": PRIVATE_PAYLOAD}},
        ]
    else:
        chunks = [
            SimpleNamespace(choices=[], vendor_extra=PRIVATE_PAYLOAD),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=PRIVATE_PAYLOAD), finish_reason=None)]
            ),
        ]

    async def astream():
        for chunk in chunks:
            yield chunk

    sync_call.return_value = iter(chunks)
    async_call.return_value = astream()
    caplog.set_level(logging.DEBUG, logger=f"hugegraph_llm_core.providers.{name}")

    assert invoke_mode(client, mode) == PRIVATE_PAYLOAD
    assert PRIVATE_PAYLOAD not in caplog.text


@pytest.mark.parametrize("mode", ["sync", "async", "stream", "async_stream"])
def test_openai_legacy_error_output_remains_explicit_but_is_not_logged(mode, caplog):
    openai = pytest.importorskip("openai", reason="Install the openai extra to run this provider contract")
    import httpx

    from hugegraph_llm_core.providers.openai import OpenAIClient

    failure = openai.BadRequestError(
        PRIVATE_PAYLOAD,
        response=httpx.Response(400, request=httpx.Request("POST", "https://model.invalid")),
        body=None,
    )
    sync_call, async_call = Mock(side_effect=failure), AsyncMock(side_effect=failure)
    client = OpenAIClient(
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=sync_call))),
        async_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=async_call))),
        raise_on_truncation=False,
    )
    caplog.set_level(logging.DEBUG, logger="hugegraph_llm_core.providers.openai")

    assert PRIVATE_PAYLOAD in invoke_mode(client, mode)
    assert PRIVATE_PAYLOAD not in caplog.text
    assert "BadRequestError" in caplog.text
