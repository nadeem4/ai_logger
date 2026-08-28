from unittest.mock import MagicMock
import pytest
from ai_logging.providers.base import ProviderError
from ai_logging.providers.openai_provider import OpenAIProvider
from ai_logging.providers.anthropic_provider import AnthropicProvider

def test_openai_provider_calls_chat_completions():
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [MagicMock(message=MagicMock(content="analysis"))]
    p = OpenAIProvider(model="gpt-4o-mini", api_key="sk-test", client=client)
    assert p.complete("prompt text") == "analysis"
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["messages"][0]["content"] == "prompt text"

def test_openai_errors_wrapped():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("rate limit")
    p = OpenAIProvider(model="gpt-4o-mini", api_key="sk-test", client=client)
    with pytest.raises(ProviderError):
        p.complete("x")

def test_missing_sdk_raises_helpful_error(monkeypatch):
    import builtins, sys
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ProviderError, match="pip install"):
        OpenAIProvider(model="m", api_key="k")  # no injected client -> tries import


def test_anthropic_provider_calls_messages_create():
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text="analysis")]
    p = AnthropicProvider(model="claude-3-haiku", api_key="sk-test", client=client)
    assert p.complete("prompt text") == "analysis"
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-3-haiku"
    assert kwargs["messages"][0]["content"] == "prompt text"
    assert kwargs["max_tokens"] == 1024


def test_anthropic_provider_passes_custom_max_tokens():
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text="analysis")]
    p = AnthropicProvider(model="claude-3-haiku", api_key="sk-test", client=client, max_tokens=256)
    p.complete("prompt text")
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 256


def test_anthropic_errors_wrapped():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("rate limit")
    p = AnthropicProvider(model="claude-3-haiku", api_key="sk-test", client=client)
    with pytest.raises(ProviderError):
        p.complete("x")


def test_anthropic_missing_sdk_raises_helpful_error(monkeypatch):
    import builtins, sys
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProviderError, match="pip install anthropic"):
        AnthropicProvider(model="m", api_key="k")  # no injected client -> tries import
