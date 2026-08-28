import logging

from logscribe.router.llm_router import LLMRouter


class Fake:
    def __init__(self, name):
        self.model = name
        self.prompts = []

    def complete(self, p):
        self.prompts.append(p)
        return f"resp-{self.model}"


def test_error_batch_routes_to_capable():
    r = LLMRouter(fast=Fake("fast"), capable=Fake("capable"))
    out = r.route_prompt("p", [{"levelno": logging.ERROR}])
    assert out == "resp-capable"


def test_info_batch_routes_to_fast():
    r = LLMRouter(fast=Fake("fast"), capable=Fake("capable"))
    assert r.route_prompt("p", [{"levelno": logging.INFO}]) == "resp-fast"


def test_no_providers_returns_none():
    r = LLMRouter(fast=None, capable=None)
    assert r.route_prompt("p", [{"levelno": logging.INFO}]) is None


def test_provider_error_propagates_for_handler_retry():
    from logscribe.providers.base import ProviderError

    class Boom:
        model = "x"

        def complete(self, p):
            raise ProviderError("down")

    r = LLMRouter(fast=Boom(), capable=Boom())
    import pytest

    with pytest.raises(ProviderError):
        r.route_prompt("p", [{"levelno": logging.INFO}])


# --- Fix round 1 regression coverage ---
# These cover the settings-built path for the anthropic provider (the
# override-detection fix using Settings.model_fields_set) and warn-once.
# The autouse clean_settings fixture in conftest.py already deletes
# OPENAI_API_KEY / ANTHROPIC_API_KEY and resets the settings singleton
# before each test, so each test here sets only what it needs via
# monkeypatch.setenv. Constructing an AnthropicProvider with no injected
# client builds a real anthropic.Anthropic client object but makes no
# network call — .complete() is never invoked on it below.


def test_anthropic_defaults_used_when_not_overridden(monkeypatch):
    from logscribe.providers.anthropic_provider import AnthropicProvider

    monkeypatch.setenv("LOGSCRIBE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    r = LLMRouter()

    assert isinstance(r.fast, AnthropicProvider)
    assert isinstance(r.capable, AnthropicProvider)
    assert r.fast.model == "claude-3-5-haiku-latest"
    assert r.capable.model == "claude-sonnet-4-5"


def test_anthropic_explicit_fast_model_override_survives(monkeypatch):
    # Regression guard for the "Important" review finding: a user on the
    # anthropic provider who explicitly sets LOGSCRIBE_FAST_MODEL to the
    # literal string that also happens to be the OpenAI default must not
    # have it silently overwritten with the Anthropic default.
    monkeypatch.setenv("LOGSCRIBE_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LOGSCRIBE_FAST_MODEL", "gpt-4o-mini")

    r = LLMRouter()

    assert r.fast.model == "gpt-4o-mini"
    # capable was not overridden, so it still gets the anthropic default.
    assert r.capable.model == "claude-sonnet-4-5"


def test_warn_once_logs_single_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="logscribe.router.llm_router"):
        r = LLMRouter(fast=None, capable=None)
        r.route_prompt("p", [{"levelno": logging.INFO}])
        r.route_prompt("p", [{"levelno": logging.INFO}])

    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert len(warnings) == 1
